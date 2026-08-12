#include <iostream>
#include <vector>
#include <tuple>
#include <algorithm>
#include <set>
#include <string>
#include <sstream>
#include <chrono>
#include <iomanip>
#include <fstream> // 添加头文件
#ifdef _WIN32
#include <windows.h>
#endif
using namespace std;

double high_resolution_seconds() {
#ifdef _WIN32
    LARGE_INTEGER frequency, counter;
    QueryPerformanceFrequency(&frequency);
    QueryPerformanceCounter(&counter);
    return static_cast<double>(counter.QuadPart) / frequency.QuadPart;
#else
    return chrono::duration<double>(
        chrono::steady_clock::now().time_since_epoch()
    ).count();
#endif
}

// 货物的6种放置姿态
struct CargoPose {
    enum Type { tall_wide, tall_thin, mid_wide, mid_thin, short_wide, short_thin };
};

struct Point {
    int x, y, z;
    Point(int x_ = -1, int y_ = -1, int z_ = -1) : x(x_), y(y_), z(z_) {}
    bool is_valid() const { return x >= 0 && y >= 0 && z >= 0; }
    bool operator==(const Point& o) const { return x == o.x && y == o.y && z == o.z; }
};

struct Cargo {
    int _length, _width, _height;
    CargoPose::Type _pose;
    Point _point;
    string _box_id;
    string _type_id;
    unsigned int _allowed_pose_mask;
    Cargo(int l, int w, int h)
        : _length(l), _width(w), _height(h), _pose(CargoPose::tall_thin),
          _point(-1, -1, -1), _allowed_pose_mask((1u << 6) - 1) {}
    Cargo(int l, int w, int h, const string& box_id, const string& type_id,
          unsigned int allowed_pose_mask)
        : _length(l), _width(w), _height(h), _pose(CargoPose::tall_thin),
          _point(-1, -1, -1), _box_id(box_id), _type_id(type_id),
          _allowed_pose_mask(allowed_pose_mask) {}
    tuple<int,int,int> shape() const {
        // 参考Python版，返回不同姿态下的三边
        int l = _length, w = _width, h = _height;
        switch (_pose) {
            case CargoPose::tall_thin:  return make_tuple(l, w, h);
            case CargoPose::tall_wide:  return make_tuple(w, l, h);
            case CargoPose::mid_thin:   return make_tuple(h, w, l);
            case CargoPose::mid_wide:   return make_tuple(w, h, l);
            case CargoPose::short_thin: return make_tuple(h, l, w);
            case CargoPose::short_wide: return make_tuple(l, h, w);
        }
        return make_tuple(l, w, h);
    }
    int length() const { return get<0>(shape()); }
    int width()  const { return get<1>(shape()); }
    int height() const { return get<2>(shape()); }
    int volume() const { return _length * _width * _height; }
    bool is_pose_allowed(CargoPose::Type pose) const {
        return (_allowed_pose_mask & (1u << static_cast<unsigned int>(pose))) != 0;
    }
    // 坐标相关h
    int x() const { return _point.x; }
    int y() const { return _point.y; }
    int z() const { return _point.z; }
    void set_pose(CargoPose::Type pose) { _pose = pose; }
    void set_point(const Point& p) { _point = p; }
};
bool is_cargos_collide(const Cargo& c0, const Cargo& c1) {
    // 获取两个货物的起止坐标
    int x0 = c0.x(), y0 = c0.y(), z0 = c0.z();
    int x1 = c1.x(), y1 = c1.y(), z1 = c1.z();
    int x0e = x0 + c0.length(), y0e = y0 + c0.width(), z0e = z0 + c0.height();
    int x1e = x1 + c1.length(), y1e = y1 + c1.width(), z1e = z1 + c1.height();
    // 判断在每个维度上是否有重叠
    bool overlap_x = x0 < x1e && x1 < x0e;
    bool overlap_y = y0 < y1e && y1 < y0e;
    bool overlap_z = z0 < z1e && z1 < z0e;
    return overlap_x && overlap_y && overlap_z;
}
struct Container {
    int _length, _width, _height;
    vector<Point> _available_points;
    vector<Cargo> _setted_cargos;
    int _horizontal_planar = 0;
    int _vertical_planar = 0;
    Container(int l, int w, int h) : _length(l), _width(w), _height(h) {
        _available_points.push_back(Point(0,0,0));
    }
    int length() const { return _length; }
    int width()  const { return _width; }
    int height() const { return _height; }
    int volume() const { return _length * _width * _height; }
    void refresh() {
        _horizontal_planar = 0;
        _vertical_planar = 0;
        _available_points.clear();
        _available_points.push_back(Point(0,0,0));
        _setted_cargos.clear();
    }
    void sort_available_points() {
        sort(_available_points.begin(), _available_points.end(), [](const Point& a, const Point& b) {
            if (a.z != b.z) return a.z < b.z;
            if (a.x != b.x) return a.x < b.x;
            return a.y < b.y;
        });
    }
    bool is_cargos_collide(const Cargo& c0, const Cargo& c1) {
        // 获取两个货物的起止坐标
        int x0 = c0.x(), y0 = c0.y(), z0 = c0.z();
        int x1 = c1.x(), y1 = c1.y(), z1 = c1.z();
        int x0e = x0 + c0.length(), y0e = y0 + c0.width(), z0e = z0 + c0.height();
        int x1e = x1 + c1.length(), y1e = y1 + c1.width(), z1e = z1 + c1.height();
        // 判断在每个维度上是否有重叠
        bool overlap_x = x0 < x1e && x1 < x0e;
        bool overlap_y = y0 < y1e && y1 < y0e;
        bool overlap_z = z0 < z1e && z1 < z0e;
        return overlap_x && overlap_y && overlap_z;
    }
    bool is_encasable(const Point& site, const Cargo& cargo) {
        Cargo temp = cargo;
        temp._point = site;
        if (temp.x() + temp.length() > _length || temp.y() + temp.width() > _width || temp.z() + temp.height() > _height)
            return false;
        for (const auto& setted : _setted_cargos) {
            if (is_cargos_collide(temp, setted)) return false;
        }
        return true;
    }
    Point encase(Cargo& cargo) {
        Point flag(-1,-1,-1);
        int history_h = _horizontal_planar, history_v = _vertical_planar;
        auto is_planar_changed = [&]() {
            return (!flag.is_valid() && _horizontal_planar == history_h && _vertical_planar == history_v);
        };
        for (const auto& point : _available_points) {
            if (is_encasable(point, cargo) && point.x + cargo.length() < _horizontal_planar && point.z + cargo.height() < _vertical_planar) {
                flag = point;
                break;
            }
        }
        if (!flag.is_valid()) {
            if (_horizontal_planar == 0 || _horizontal_planar == _length) {
                if (is_encasable(Point(0,0,_vertical_planar), cargo)) {
                    flag = Point(0,0,_vertical_planar);
                    _vertical_planar += cargo.height();
                    _horizontal_planar = cargo.length();
                } else if (_vertical_planar < _height) {
                    _vertical_planar = _height;
                    _horizontal_planar = _length;
                    if (is_planar_changed()) flag.z = 0;
                }
            } else {
                for (const auto& point : _available_points) {
                    if (point.x == _horizontal_planar && point.y == 0 && is_encasable(point, cargo) && point.z + cargo.height() <= _vertical_planar) {
                        flag = point;
                        _horizontal_planar += cargo.length();
                        break;
                    }
                }
                if (!flag.is_valid()) {
                    _horizontal_planar = _length;
                    if (is_planar_changed()) flag.z = 0;
                }
            }
        }
        if (flag.is_valid()) {
            cargo._point = flag;
            auto it = find(_available_points.begin(), _available_points.end(), flag);
            if (it != _available_points.end()) _available_points.erase(it);
            adjust_setting_cargo(cargo);
            _setted_cargos.push_back(cargo);
            _available_points.push_back(Point(cargo.x() + cargo.length(), cargo.y(), cargo.z()));
            _available_points.push_back(Point(cargo.x(), cargo.y() + cargo.width(), cargo.z()));
            _available_points.push_back(Point(cargo.x(), cargo.y(), cargo.z() + cargo.height()));
            sort_available_points();
        }
        return flag;
    }
    void adjust_setting_cargo(Cargo& cargo) {
        Point site = cargo._point;
        Cargo temp = cargo;
        if (!is_encasable(site, cargo)) return;
        int xyz[3] = {site.x, site.y, site.z};
        for (int i = 0; i < 3; ++i) {
            bool is_continue = true;
            while (xyz[i] > 1 && is_continue) {
                xyz[i] -= 1;
                temp._point = Point(xyz[0], xyz[1], xyz[2]);
                bool collide = false;
                for (const auto& setted : _setted_cargos) {
                    if (is_cargos_collide(setted, temp)) { collide = true; break; }
                }
                if (!collide) continue;
                xyz[i] += 1;
                is_continue = false;
            }
        }
        cargo._point = Point(xyz[0], xyz[1], xyz[2]);
    }
};

// 判断两个长方体是否重叠
bool is_rectangles_overlap(std::tuple<int,int,int,int> rec1, std::tuple<int,int,int,int> rec2);


// 策略基类
struct Strategy {
    virtual vector<CargoPose::Type> choose_cargo_poses(const Cargo& cargo, const Container& container) const {
        // Preserve the historical trial order, filtering only orientations that
        // the canonical instance explicitly disallows.
        const vector<CargoPose::Type> historical_order = {
            CargoPose::tall_wide, CargoPose::tall_thin,
            CargoPose::mid_wide, CargoPose::mid_thin,
            CargoPose::short_wide, CargoPose::short_thin
        };
        vector<CargoPose::Type> allowed;
        for (CargoPose::Type pose : historical_order) {
            if (cargo.is_pose_allowed(pose)) allowed.push_back(pose);
        }
        return allowed;
    }
    virtual vector<Cargo> encasement_sequence(const vector<Cargo>& cargos) const {
        return cargos;
    }
};

struct VolumeGreedyStrategy : public Strategy {
    vector<Cargo> encasement_sequence(const vector<Cargo>& cargos) const override {
        vector<Cargo> sorted = cargos;
        sort(sorted.begin(), sorted.end(), [](const Cargo& a, const Cargo& b) { return a.volume() > b.volume(); });
        return sorted;
    }
};

// 主装箱函数
float encase_cargos_into_container(vector<Cargo> cargos, Container& container, const Strategy& strategy) {
    // 需要用指针或引用操作原始cargos，保证container中存储的cargo与外部一致
    vector<Cargo*> sorted_cargos_ptr;
    vector<Cargo> sorted_cargos = strategy.encasement_sequence(cargos);
    // 建立指针数组，指向原始cargos
    for (auto& c : cargos) sorted_cargos_ptr.push_back(&c);
    // 按照排序结果重新排列指针
    sort(sorted_cargos_ptr.begin(), sorted_cargos_ptr.end(), [&](Cargo* a, Cargo* b){
        return a->volume() > b->volume();
    });
    size_t i = 0;
    while (i < sorted_cargos_ptr.size()) {
        size_t j = 0;
        Cargo* cargo = sorted_cargos_ptr[i];
        auto poses = strategy.choose_cargo_poses(*cargo, container);
        bool is_valid = false;
        Point flag(-1,-1,-1);
        while (j < poses.size()) {
            cargo->set_pose(poses[j]);
            flag = container.encase(*cargo);
            if (flag.is_valid()) { is_valid = true; break; }
            ++j;
        }
        if (is_valid) {
            ++i;
        } else if (flag == Point(-1,-1,0)) {
            continue;
        } else {
            ++i;
        }
    }
    int total = 0;
    for (const auto& c : container._setted_cargos) total += c.volume();
    return float(total) / container.volume();
}

void save_encasement_as_file(const Container& container, const std::string& filename) {
    std::ofstream file(filename);
    file << "index,x,y,z,length,width,height\n";
    int idx = 1;
    for (const auto& cargo : container._setted_cargos) {
        // 只导出合法箱子
        if (cargo.x() < 0 || cargo.y() < 0 || cargo.z() < 0) continue;
        file << idx++ << ","
             << cargo.x() << ","
             << cargo.y() << ","
             << cargo.z() << ","
             << cargo.length() << ","
             << cargo.width() << ","
             << cargo.height() << "\n";
    }
    file.close();
}

// Explicit mapping between the canonical orientation names and the historical
// internal pose enum. Repeated dimensions do not collapse orientation IDs: the
// exact allowed/chosen orientation remains identifiable even when shapes match.
string canonical_orientation(CargoPose::Type pose) {
    switch (pose) {
        case CargoPose::tall_thin:  return "LWH";
        case CargoPose::short_wide: return "LHW";
        case CargoPose::tall_wide:  return "WLH";
        case CargoPose::mid_wide:   return "WHL";
        case CargoPose::short_thin: return "HLW";
        case CargoPose::mid_thin:   return "HWL";
    }
    return "";
}

int run_machine_mode() {
    string line;
    int container_length = 0, container_width = 0, container_height = 0;
    vector<Cargo> cargos;
    bool have_container = false;

    while (getline(cin, line)) {
        if (line.empty()) continue;
        istringstream fields(line);
        string record_type;
        fields >> record_type;
        if (record_type == "CONTAINER") {
            if (!(fields >> container_length >> container_width >> container_height) ||
                container_length <= 0 || container_width <= 0 || container_height <= 0) {
                cerr << "ERROR invalid CONTAINER record" << endl;
                return 2;
            }
            have_container = true;
        } else if (record_type == "BOX") {
            string box_id, type_id;
            int length, width, height;
            unsigned int allowed_pose_mask;
            if (!(fields >> box_id >> type_id >> length >> width >> height >> allowed_pose_mask) ||
                box_id.empty() || type_id.empty() || length <= 0 || width <= 0 || height <= 0 ||
                allowed_pose_mask == 0 || allowed_pose_mask >= (1u << 6)) {
                cerr << "ERROR invalid BOX record" << endl;
                return 2;
            }
            cargos.emplace_back(length, width, height, box_id, type_id, allowed_pose_mask);
        } else if (record_type == "END") {
            break;
        } else {
            cerr << "ERROR unknown record type: " << record_type << endl;
            return 2;
        }
    }

    if (!have_container) {
        cerr << "ERROR missing CONTAINER record" << endl;
        return 2;
    }

    Container container(container_length, container_width, container_height);
    VolumeGreedyStrategy strategy;
    const double core_start = high_resolution_seconds();
    encase_cargos_into_container(cargos, container, strategy);
    const double core_runtime_seconds = high_resolution_seconds() - core_start;

    long long packed_volume = 0;
    for (const auto& cargo : container._setted_cargos) {
        if (cargo.x() < 0 || cargo.y() < 0 || cargo.z() < 0) continue;
        packed_volume += cargo.volume();
        cout << "PLACEMENT\t" << cargo._box_id
             << "\t" << cargo._type_id
             << "\t" << canonical_orientation(cargo._pose)
             << "\t" << cargo.x()
             << "\t" << cargo.y()
             << "\t" << cargo.z()
             << "\t" << cargo.length()
             << "\t" << cargo.width()
             << "\t" << cargo.height() << "\n";
    }
    cout << "CORE_RUNTIME_SECONDS\t" << setprecision(17) << core_runtime_seconds << "\n";
    cout << "SUMMARY\t" << container._setted_cargos.size()
         << "\t" << packed_volume
         << "\t" << static_cast<long long>(container_length) * container_width * container_height
         << "\n";
    return 0;
}

// 示例交互路径（保留原有行为）
int run_interactive_mode() {
    cout<< "3D Bin Packing Example" << endl;
    int container_length, container_width, container_height;
    cout << "input container length, width, height: " << endl;
    cin >> container_length >> container_width >> container_height;
    // 创建一个容器
    Container container(container_length,container_width,container_height);

    vector<Cargo> cargos;
    int num_cargos_type;
    cout << "input cargo type number: " << endl;
    cin >> num_cargos_type;
    vector<int> num_cargos(num_cargos_type);
    for (int i = 0; i < num_cargos_type; ++i) {
        cout << "input cargo type " << i + 1 << " number: " << endl;
        cin >> num_cargos[i];
    }

    for (int i = 0; i < num_cargos_type; ++i) {
        int length, width, height;
        cout << "input cargo type " << i + 1 << " length, width, height: " << endl;
        cin >> length >> width >> height;
        for (int j = 0; j < num_cargos[i]; ++j) {
            cargos.emplace_back(length, width, height);
        }
    }
    VolumeGreedyStrategy strategy;
    float ratio = encase_cargos_into_container(cargos, container, strategy);
    cout << "Container volume utilization rate: " << ratio << endl;
    cout << "Number of boxed items: " << container._setted_cargos.size() << endl;

    // 导出csv
    save_encasement_as_file(container, "encasement.csv");





    string is_continue;
    cout<< "input anything to exit"<<endl;
    cin>> is_continue;
    return 0;
}

int main(int argc, char* argv[]) {
    if (argc == 2 && string(argv[1]) == "--machine") {
        return run_machine_mode();
    }
    if (argc != 1) {
        cerr << "usage: " << argv[0] << " [--machine]" << endl;
        return 2;
    }
    return run_interactive_mode();
}

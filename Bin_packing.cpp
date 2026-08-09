#include<iostream>
#include<vector>
#include<cmath>
#include<string>
#include<algorithm>
#include<functional>
using namespace std;
struct Box{
    double length;
    double width;
    double height;
    double weight=0;
    Box(double l, double w, double h) : length(l), width(w), height(h) {}
    Box(double l, double w, double h, double wt) : length(l), width(w), height(h), weight(wt) {}
    double volume() const {
        return length * width * height;
    }
    vector<int> position;
    bool allow_tobe_rotated[3] = {0 ,1, 0}; // allow_to_be_rotated[i] = true if the box can be rotated around the i-th axis x, y, or z
    bool rotation[3];                  // rotation[i] = true if the box is rotated around the i-th axis x, y, or z
    void addRotation(bool x, bool y, bool z) {
        rotation[0] = x;
        rotation[1] = y;
        rotation[2] = z;
    }
    void addPosition(int x, int y, int z) {
        position.push_back(x);
        position.push_back(y);
        position.push_back(z);
    }

};
struct Container{
    double length;
    double width;
    double height;
    double total_weight=0; // weight of the container本身
    double max_weight=1e9; // maximum weight the container can hold, initialized to a large value
    double current_weight=0; // 当前已装入的盒子总重量
    // 增加盒子重量
    void addBoxWeight(double w) { current_weight += w; }
    // 移除盒子重量
    void removeBoxWeight(double w) { current_weight -= w; }
    int total_boxes = 0; // total number of boxes the container can hold, initialized to 0
    // Constructor to initialize the container with length, width, height, and weight
    Container(double l, double w, double h) : length(l), width(w), height(h) {}
    Container(double l, double w, double h, double wt) : length(l), width(w), height(h), max_weight(wt) {}
    bool canFit(const Box& b) const {
        return (b.length <= length && b.width <= width && b.height <= height);
    }
    double volume() const {
        return length * width * height;
    }
};
struct Left_Space{
    double length;
    double width;
    double height;
    double x,y,z; // 记录剩余空间的起始位置
    Left_Space(double l, double w, double h) : length(l), width(w), height(h) {}
    bool canFit(const Box& b) const {
        return (b.length <= length && b.width <= width && b.height <= height);
    }
    double volume() const {
        return length * width * height;
    }
};


class BinPacking {
    /*
    ===================== BinPacking类使用说明 =====================
    1. 构造：
        BinPacking bp(container, boxes, epoch);
        - container: Container对象，指定集装箱尺寸。
        - boxes: vector<vector<Box>>，每个子vector为同类型盒子集合。
        - epoch: 递归深度上限（可选，当前未强制使用）。

    2. 调用：
        - bp.RearrangeBoxes(); // 按体积降序排序盒子组（建议先调用）
        - Left_Space init_space(container.length, container.width, container.height);
        - vector<Left_Space> spaces = {init_space};
        - bp.PackBoxes(spaces, bp.boxes, bp.packed_boxes, bp.min_loss, bp.best_packed);

    3. 结果：
        - bp.best_packed：最佳装箱方案（已放入的盒子）
        - bp.min_loss：最小剩余空间体积

    4. 主要函数说明：
        - Combine_boxes：在指定空间内合并同类型盒子为最大长方体，返回error，error>allow_error表示不能合并。
        - PackBoxes：主递归函数，优先合并，不能合并则单独摆放并分割空间，递归找最优。

    5. 注意事项/潜在不明确点：
        - 合并后剩余空间的分割方式较为简化，实际可根据需求优化空间分割策略。
        - packed_boxes/best_packed为引用参数，递归时需注意回溯。
        - epoch参数未被强制限制递归深度，如需限制可在递归入口加判断。
        - 盒子旋转只考虑allow_tobe_rotated，未考虑所有物理可行旋转。
        - Combine_boxes合并后，移除盒子的数量用体积比，若盒子体积不完全一致可能有误差。
        - 若有多种类型盒子，建议提前归类并保证每组盒子尺寸一致。
        - 若需输出装箱坐标/姿态，可在Box结构体中补充相关信息。
    =============================================================
    */
public:
    vector<vector<Box>> boxes;      // a 2D vector to hold different types of boxes, each type can have multiple boxes, 
                                    // where boxes[i] is a vector of boxes of type i
    vector<Box> combined_boxes; // 用于存储合并后的盒子
    Container container;
    int epoch;                      // the maxium epoch of the recursion depth
    double totalVolume = 0.0;
    double min_loss = 1e9;          // 初始化为一个很大的值
    vector<Box> best_packed; // 最佳装箱结果
    vector<Box> packed_boxes; // 当前已装入的盒子

    void RearrangeBoxes() {
        // 按每组第一个盒子的体积降序排序
        sort(boxes.begin(), boxes.end(), [](const vector<Box>& a, const vector<Box>& b) {
            double va = a.empty() ? 0 : a[0].volume();
            double vb = b.empty() ? 0 : b[0].volume();
            return va > vb;
        });
    }
    
    // Constructor to initialize the BinPacking with a container and a vector of boxes
    BinPacking(const Container& c, vector<vector<Box>> b, int e) : container(c), epoch(e) {
        boxes = b;
        RearrangeBoxes();
    }
    


    // 其他成员函数和方法

    // 损失函数：所有剩余空间总体积
    double Total_Loss(const vector<Left_Space>& spaces) {
        double loss = 0.0;
        for (const auto& s : spaces) loss += s.volume();
        return loss;
    }
    double Loss(const Left_Space spaces) {
        return spaces.volume();
    }
    // 在available_space内合并同类型盒子为最大完整长方体，返回是否成功
    double Combine_boxes(const Left_Space& available_space, vector<Box>& boxes, double allow_error = 0.15) {
        if (boxes.empty()) return 1.0;
        Box base = boxes[0];
        int n = boxes.size();
        int best_x=1, best_y=1, best_z=1, best_rot=0, best_cnt=1;
        double best_l=base.length, best_w=base.width, best_h=base.height, best_error=1.0, best_vol=0;
        struct RotInfo { double l, w, h; bool rot[3]; };
        vector<RotInfo> rots = {
            {base.length, base.width, base.height, {0,0,0}},
            {base.length, base.height, base.width, {0,1,0}},
            {base.width, base.length, base.height, {1,0,0}},
            {base.width, base.height, base.length, {1,1,0}},
            {base.height, base.length, base.width, {1,0,1}},
            {base.height, base.width, base.length, {0,0,1}}
        };
        double avail_vol = available_space.volume();
        for (int rot = 0; rot < rots.size(); ++rot) {
            bool valid = true;
            for (int axis = 0; axis < 3; ++axis) {
                if (rots[rot].rot[axis] && !base.allow_tobe_rotated[axis]) {
                    valid = false;
                    break;
                }
            }
            if (!valid) continue;
            double l0 = rots[rot].l, w0 = rots[rot].w, h0 = rots[rot].h;
            for (int x = 1; x <= n; ++x) {
                for (int y = 1; y <= n/x; ++y) {
                    for (int z = 1; z <= n/(x*y); ++z) {
                        int cnt = x*y*z;
                        if (cnt > n) continue;
                        double L = l0*x, W = w0*y, H = h0*z;
                        if (L > available_space.length+1e-6 || W > available_space.width+1e-6 || H > available_space.height+1e-6) continue;
                        if (cnt != n && n % cnt != 0) continue;
                        double merged_vol = L*W*H;
                        double left_vol = avail_vol - merged_vol;
                        if (left_vol < 0) continue;
                        double error = left_vol / merged_vol;
                        if (error < best_error) {
                            best_x = x; best_y = y; best_z = z; best_rot = rot; best_cnt = cnt;
                            best_l = L; best_w = W; best_h = H; best_error = error; best_vol = merged_vol;
                        }
                    }
                }
            }
        }
        if (best_error <= allow_error && best_cnt > 1) {
            Box merged_box(best_l, best_w, best_h, base.weight * best_cnt);
            combined_boxes.push_back(merged_box);
            return best_error;
        }
        return 1.0; //注意浮点数精度问题，后续进行操作时建议强制转换int类型
    }

    // 试图分解盒子组，返回值为 vector<int>, 表示新的各个盒子组中盒子的数量
    // 分解盒子组为多个盒子组，尝试将盒子组拆分成多个合数或者合数+1的盒子组
    // 例如：13 -> {12+1, 6+6+1, 4+4+4+1}, 最多返回size_return种组合
    // 返回值为 vector<int>，表示每个盒子组的盒子数量
    vector<int> decompose_boxes(vector<Box>& boxes, int size_return = 5) {
        int n = boxes.size();
        vector<vector<int>> results;
        vector<int> composites = {12,10,9,8,6,4,3,2};
        function<void(int, vector<int>&)> dfs = [&](int remain, vector<int>& path) {
            if (results.size() >= size_return) return;
            if (remain == 0) {
                results.push_back(path);
                return;
            }
            for (int c : composites) {
                if (c <= remain) {
                    path.push_back(c);
                    dfs(remain - c, path);
                    path.pop_back();
                }
            }
            if (remain > 0 && path.size() < size_return) {
                vector<int> tmp = path;
                for (int i = 0; i < remain; ++i) tmp.push_back(1);
                results.push_back(tmp);
            }
        };
        vector<int> path;
        dfs(n, path);
        if (!results.empty()) return results[0];
        return {n};
    }

    // 递归主函数：贪心装箱，允许部分盒子不装入
    // 主递归装箱函数，贪心优先合并，不能合并则单独摆放并分割空间，递归找最优
    // 返回值为 int, 表示当前的装箱数量
    int PackBoxes(vector<Left_Space>& spaces, vector<vector<Box>> boxes_left, vector<Box> packed_boxes, double& min_loss, vector<Box>& best_packed) {
        // 终止条件：无空间或无盒子
        if (spaces.empty() || boxes_left.empty()) {
            double loss = Total_Loss(spaces);
            if (loss < min_loss) {
                min_loss = loss;
                best_packed = packed_boxes;
            }
            return packed_boxes.size();
        }

        // 取体积最大的盒子组（已降序）
        int max_group = -1;
        double max_vol = -1;
        for (int i = 0; i < boxes_left.size(); ++i) {
            if (!boxes_left[i].empty() && boxes_left[i][0].volume() > max_vol) {
                max_vol = boxes_left[i][0].volume();
                max_group = i;
            }
        }
        if (max_group == -1) {
            double loss = Total_Loss(spaces);
            if (loss < min_loss) {
                min_loss = loss;
                best_packed = packed_boxes;
            }
            return packed_boxes.size();
        }
        auto cur_boxes = boxes_left[max_group];
        int max_packed = packed_boxes.size();
        bool merged = false;
        double best_error = 1.0;
        int best_space_idx = -1;
        // 遍历每个left_space，尝试合并
        for (int s = 0; s < spaces.size(); ++s) {
            double error = Combine_boxes(spaces[s], cur_boxes);
            if (error < best_error) {
                best_error = error;
                best_space_idx = s;
            }
        }
        if (best_error < 0.15 && best_space_idx != -1) {
            // 合并成功
            merged = true;
            // 合并后移除盒子组
            vector<vector<Box>> new_boxes_left = boxes_left;
            new_boxes_left.erase(new_boxes_left.begin() + max_group);
            // 合并后分割剩余空间（此处简化为移除该空间）
            vector<Left_Space> new_spaces = spaces;
            new_spaces.erase(new_spaces.begin() + best_space_idx);
            // 合并的盒子加入packed_boxes
            vector<Box> new_packed = packed_boxes;
            if (!combined_boxes.empty()) {
                new_packed.push_back(combined_boxes.back());
                combined_boxes.pop_back();
            }
            int res = PackBoxes(new_spaces, new_boxes_left, new_packed, min_loss, best_packed);
            if (res > max_packed) max_packed = res;
        } else {
            // 合并不了，尝试分解
            auto decomp = decompose_boxes(cur_boxes);
            if (decomp.size() > 1) {
                int idx = 0;
                vector<vector<Box>> new_groups;
                for (int cnt : decomp) {
                    vector<Box> group;
                    for (int j = 0; j < cnt && idx < cur_boxes.size(); ++j, ++idx) {
                        group.push_back(cur_boxes[idx]);
                    }
                    new_groups.push_back(group);
                }
                // 只对合数组尝试合并
                for (int g = 0; g < new_groups.size(); ++g) {
                    if (new_groups[g].size() > 1) {
                        for (int s = 0; s < spaces.size(); ++s) {
                            double error = Combine_boxes(spaces[s], new_groups[g]);
                            if (error < 0.15) {
                                // 合并成功
                                vector<vector<Box>> new_boxes_left = boxes_left;
                                new_boxes_left.erase(new_boxes_left.begin() + max_group);
                                // 其余分组重新插入
                                for (int gg = 0; gg < new_groups.size(); ++gg) {
                                    if (gg != g && !new_groups[gg].empty()) new_boxes_left.push_back(new_groups[gg]);
                                }
                                vector<Left_Space> new_spaces = spaces;
                                new_spaces.erase(new_spaces.begin() + s);
                                vector<Box> new_packed = packed_boxes;
                                if (!combined_boxes.empty()) {
                                    new_packed.push_back(combined_boxes.back());
                                    combined_boxes.pop_back();
                                }
                                int res = PackBoxes(new_spaces, new_boxes_left, new_packed, min_loss, best_packed);
                                if (res > max_packed) max_packed = res;
                            }
                        }
                    }
                }
            }
            // 如果实在没有合并成功，则尝试单独摆放当前组的盒子
            // 只考虑第一个盒子
            for (int s = 0; s < spaces.size(); ++s) {
                for (int rot = 0; rot < 6; ++rot) {
                    Box b = cur_boxes[0];
                    // 旋转
                    if (rot == 1) swap(b.width, b.height);
                    if (rot == 2) swap(b.length, b.width);
                    if (rot == 3) swap(b.length, b.height);
                    if (rot == 4) swap(b.width, b.length);
                    if (rot == 5) swap(b.height, b.width);
                    if (spaces[s].canFit(b)) {
                        // 放入
                        vector<Left_Space> new_spaces = spaces;
                        // 简化：移除该空间
                        new_spaces.erase(new_spaces.begin() + s);
                        vector<vector<Box>> new_boxes_left = boxes_left;
                        new_boxes_left[max_group].erase(new_boxes_left[max_group].begin());
                        if (new_boxes_left[max_group].empty()) new_boxes_left.erase(new_boxes_left.begin() + max_group);
                        vector<Box> new_packed = packed_boxes;
                        new_packed.push_back(b);
                        int res = PackBoxes(new_spaces, new_boxes_left, new_packed, min_loss, best_packed);
                        if (res > max_packed) max_packed = res;
                    }
                }
            }
        }
        return max_packed;
    }
};
int main() {
    Container container(1200, 235, 269); // 创建一个集装箱，
    vector<vector<Box>> boxes;
    for(int i = 0; i < 100; i++) {
        Box box1(50, 40, 25);
        boxes.push_back({box1});
    }
    BinPacking bp(container, boxes, 1400);
    // bp.RearrangeBoxes(); // 构造函数里已调用
    vector<Left_Space> spaces = {Left_Space(container.length, container.width, container.height)};
    bp.PackBoxes(spaces, bp.boxes, bp.packed_boxes, bp.min_loss, bp.best_packed);
    cout << "num boxes packed: " << bp.best_packed.size() << endl;
    cout << "min left space volume: " << bp.min_loss << endl;
    return 0;
}
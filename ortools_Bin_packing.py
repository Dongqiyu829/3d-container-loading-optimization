# %%
# 3D装箱问题求解器（使用OR-Tools CP-SAT）
from ortools.sat.python import cp_model
import pandas as pd
import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d import Axes3D
import os

def solve_3d_bpp(container_dims, box_types, time_limit_seconds=300, maximize_volume=True):
    """
    3D装箱问题求解函数
    
    参数:
    - container_dims: 容器尺寸 (L, W, H)
    - box_types: 箱子类型列表，每个元素包含 {type_id, l, w, h, quantity}
    - time_limit_seconds: 求解时间限制（秒）
    - maximize_volume: True=最大化体积，False=最大化箱子数量
    
    返回:
    - status: 求解状态
    - results_df: 结果DataFrame
    - solver_response: 求解器响应详情
    """
    
    L, W, H = container_dims
    
    # 创建CP模型
    model = cp_model.CpModel()
    
    # 创建箱子实例列表（每种类型创建quantity个实例）
    all_boxes = []
    for bt in box_types:
        for instance in range(bt['quantity']):
            box = {
                'type_id': bt['type_id'],
                'instance_id': instance,
                'l': bt['l'],
                'w': bt['w'], 
                'h': bt['h'],
                'volume': bt['l'] * bt['w'] * bt['h']
            }
            all_boxes.append(box)
    
    N = len(all_boxes)  # 总箱子实例数
    P = 6  # 6种方向
    
    print(f"Created variables for {N} box instances.")
    
    # --- 决策变量 ---
    
    # b[k]: 箱子k是否被选中装入容器
    b = []
    for k in range(N):
        b.append(model.NewBoolVar(f'b_{k}'))
    
    # p[k][j]: 箱子k是否使用方向j (j=0,1,2,3,4,5)
    p = []
    for k in range(N):
        p_k = []
        for j in range(P):
            p_k.append(model.NewBoolVar(f'p_{k}_{j}'))
        p.append(p_k)
    
    # x[k], y[k], z[k]: 箱子k在容器中的位置坐标
    x = []
    y = []
    z = []
    for k in range(N):
        x.append(model.NewIntVar(0, L, f'x_{k}'))
        y.append(model.NewIntVar(0, W, f'y_{k}'))
        z.append(model.NewIntVar(0, H, f'z_{k}'))
    
    # --- 方向映射 ---
    # 6种方向对应的(长,宽,高)
    orientations = [
        (0, 1, 2),  # j=0: (l, w, h)
        (0, 2, 1),  # j=1: (l, h, w)  
        (1, 0, 2),  # j=2: (w, l, h)
        (1, 2, 0),  # j=3: (w, h, l)
        (2, 0, 1),  # j=4: (h, l, w)
        (2, 1, 0),  # j=5: (h, w, l)
    ]
    
    # 为每个箱子创建实际尺寸变量
    for k, box in enumerate(all_boxes):
        original_dims = [box['l'], box['w'], box['h']]
        
        # 实际使用的长宽高
        l_actual = model.NewIntVar(1, max(original_dims), f'l_actual_{k}')
        w_actual = model.NewIntVar(1, max(original_dims), f'w_actual_{k}')
        h_actual = model.NewIntVar(1, max(original_dims), f'h_actual_{k}')
        
        box['l_actual'] = l_actual
        box['w_actual'] = w_actual
        box['h_actual'] = h_actual
        box['x'] = x[k]
        box['y'] = y[k]
        box['z'] = z[k]
        box['b'] = b[k]
        
        # 根据选择的方向确定实际尺寸
        for j, (dim1, dim2, dim3) in enumerate(orientations):
            # 如果选择方向j，则实际尺寸为对应的重排
            model.Add(l_actual == original_dims[dim1]).OnlyEnforceIf(p[k][j])
            model.Add(w_actual == original_dims[dim2]).OnlyEnforceIf(p[k][j])
            model.Add(h_actual == original_dims[dim3]).OnlyEnforceIf(p[k][j])
    
    # --- 约束条件 ---
    
    # 1. 每个箱子最多选择一个方向
    for k in range(N):
        model.Add(sum(p[k][j] for j in range(P)) == b[k])
    
    # 2. 位置边界约束
    for k in range(N):
        box = all_boxes[k]
        model.Add(x[k] + box['l_actual'] <= L).OnlyEnforceIf(b[k])
        model.Add(y[k] + box['w_actual'] <= W).OnlyEnforceIf(b[k])
        model.Add(z[k] + box['h_actual'] <= H).OnlyEnforceIf(b[k])
    
    # 3. 手动实现3D不重叠约束
    # （我们将在下面使用分离约束来实现）
    
    # 4. 不重叠约束（手动实现3D NoOverlap）
    # 对于每对箱子，如果都被选中，则它们在至少一个维度上不重叠
    for i in range(N):
        for j in range(i+1, N):
            box_i = all_boxes[i]
            box_j = all_boxes[j]
            
            # 创建分离变量：表示两个箱子在各个维度上是否分离
            sep_x_left = model.NewBoolVar(f'sep_x_left_{i}_{j}')   # i在j左边
            sep_x_right = model.NewBoolVar(f'sep_x_right_{i}_{j}') # i在j右边
            sep_y_front = model.NewBoolVar(f'sep_y_front_{i}_{j}') # i在j前面
            sep_y_back = model.NewBoolVar(f'sep_y_back_{i}_{j}')   # i在j后面
            sep_z_below = model.NewBoolVar(f'sep_z_below_{i}_{j}') # i在j下面
            sep_z_above = model.NewBoolVar(f'sep_z_above_{i}_{j}') # i在j上面
            
            # 大M值
            M = max(L, W, H)
            
            # 分离约束
            # X维度分离
            model.Add(x[i] + box_i['l_actual'] <= x[j]).OnlyEnforceIf([b[i], b[j], sep_x_left])
            model.Add(x[j] + box_j['l_actual'] <= x[i]).OnlyEnforceIf([b[i], b[j], sep_x_right])
            
            # Y维度分离
            model.Add(y[i] + box_i['w_actual'] <= y[j]).OnlyEnforceIf([b[i], b[j], sep_y_front])
            model.Add(y[j] + box_j['w_actual'] <= y[i]).OnlyEnforceIf([b[i], b[j], sep_y_back])
            
            # Z维度分离
            model.Add(z[i] + box_i['h_actual'] <= z[j]).OnlyEnforceIf([b[i], b[j], sep_z_below])
            model.Add(z[j] + box_j['h_actual'] <= z[i]).OnlyEnforceIf([b[i], b[j], sep_z_above])
            
            # 如果两个箱子都被选中，则必须在至少一个维度上分离
            both_selected = model.NewBoolVar(f'both_selected_{i}_{j}')
            model.Add(both_selected == 1).OnlyEnforceIf([b[i], b[j]])
            model.Add(both_selected == 0).OnlyEnforceIf([b[i].Not()])
            model.Add(both_selected == 0).OnlyEnforceIf([b[j].Not()])
            
            # 至少一种分离方式必须为真
            model.Add(sep_x_left + sep_x_right + sep_y_front + sep_y_back + sep_z_below + sep_z_above >= 1).OnlyEnforceIf(both_selected)
    
    # --- 目标函数 ---
    if maximize_volume:
        # 最大化总体积
        total_volume = sum(b[k] * all_boxes[k]['volume'] for k in range(N))
        model.Maximize(total_volume)
    else:
        # 最大化箱子数量
        total_boxes = sum(b[k] for k in range(N))
        model.Maximize(total_boxes)
    
    # --- 求解 ---
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit_seconds
    solver.parameters.log_search_progress = True
    
    status = solver.Solve(model)
    
    # --- 处理结果 ---
    results = []
    total_volume = 0
    
    if status == cp_model.OPTIMAL or status == cp_model.FEASIBLE:
        print(f"\n求解状态: {'最优解' if status == cp_model.OPTIMAL else '可行解'}")
        print(f"求解时间: {solver.WallTime():.2f} 秒")
        print(f"目标值: {solver.ObjectiveValue()}")
        
        for k in range(N):
            if solver.Value(b[k]):
                box = all_boxes[k]
                x_val = solver.Value(x[k])
                y_val = solver.Value(y[k])
                z_val = solver.Value(z[k])
                l_val = solver.Value(box['l_actual'])
                w_val = solver.Value(box['w_actual'])
                h_val = solver.Value(box['h_actual'])
                volume = l_val * w_val * h_val
                total_volume += volume
                
                # 确定使用的方向
                orientation = -1
                for j in range(P):
                    if solver.Value(p[k][j]):
                        orientation = j
                        break
                
                results.append({
                    "箱子编号": k,
                    "类型": box['type_id'],
                    "实例": box['instance_id'],
                    "X坐标": x_val,
                    "Y坐标": y_val,
                    "Z坐标": z_val,
                    "长": l_val,
                    "宽": w_val,
                    "高": h_val,
                    "体积": volume,
                    "方向": orientation,
                    "原始尺寸": f"{box['l']}x{box['w']}x{box['h']}"
                })
        
        results_df = pd.DataFrame(results)
        
        # 保存结果到Excel
        try:
            excel_path = "装箱结果.xlsx"
            results_df.to_excel(excel_path, index=False)
            print(f"\n结果已保存到: {os.path.abspath(excel_path)}")
        except Exception as e:
            print(f"保存Excel失败: {e}")
        
        return status, results_df, {
            'objective_value': solver.ObjectiveValue(),
            'solve_time': solver.WallTime(),
            'total_volume': total_volume,
            'volume_utilization': total_volume / (L*W*H) * 100
        }
    
    else:
        print(f"求解失败，状态: {status}")
        return status, None, None


'''
# --- 测试数据 ---
# 容器尺寸
container_dimensions = (50, 50, 50)  # 长 x 宽 x 高
L, W, H = container_dimensions

# 箱子类型定义
box_types_input = [
    {"type_id": "A", "l": 20, "w": 10, "h": 5, "quantity": 2},
    {"type_id": "B", "l": 15, "w": 15, "h": 10, "quantity": 3},
    {"type_id": "C", "l": 10, "w": 10, "h": 10, "quantity": 1},
    {"type_id": "D", "l": 5, "w": 5, "h": 5, "quantity": 10}
]

# 按体积排序（大到小）
box_types = sorted(box_types_input, key=lambda x: x["l"]*x["w"]*x["h"], reverse=True)

print("Box types sorted by volume (descending):")
for bt in box_types:
    vol = bt["l"] * bt["w"] * bt["h"]
    print(f"  Type {bt['type_id']}: {bt['l']}x{bt['w']}x{bt['h']} (Vol: {vol}) x {bt['quantity']}")

print(f"Container dimensions: {L} x {W} x {H}")
print(f"Number of box types: {len(box_types)}")
print(f"Total number of boxes: {sum(bt['quantity'] for bt in box_types)}")
print("-" * 20)

# --- 调用求解函数 ---
# maximize_volume=False 表示最大化箱子数量
# maximize_volume=True 表示最大化总体积
status, results_df, solver_response = solve_3d_bpp(
    container_dims=container_dimensions,
    box_types=box_types_input,
    time_limit_seconds=300, # 5分钟求解时间
    maximize_volume=False   # 目标：最大化箱子数量
)

# --- 输出结果 ---
print("\n" + "="*30)
if results_df is not None:
    print("装箱结果:")
    print(results_df.to_string(index=False))
    
    result = results_df.to_dict('records')
    total_volume = solver_response['total_volume']
    
    print(f"\n装箱汇总:")
    print(f"成功装入箱子数: {len(result)}")
    print(f"总装入体积: {total_volume}")
    print(f"容器体积: {L*W*H}")
    print(f"体积利用率: {solver_response['volume_utilization']:.1f}%")
else:
    print("没有找到可行解")
    result = []
    total_volume = 0
'''

# %%
# 9. 三维装箱可视化
if 'result' in locals() and result:
    fig = plt.figure(figsize=(12, 8))
    ax = fig.add_subplot(111, projection='3d')
    
    # 绘制集装箱边框
    # 12条边
    edges = [
        [(0,0,0), (L,0,0)], [(0,0,0), (0,W,0)], [(0,0,0), (0,0,H)],
        [(L,W,H), (0,W,H)], [(L,W,H), (L,0,H)], [(L,W,H), (L,W,0)],
        [(L,0,0), (L,W,0)], [(L,0,0), (L,0,H)],
        [(0,W,0), (L,W,0)], [(0,W,0), (0,W,H)],
        [(0,0,H), (L,0,H)], [(0,0,H), (0,W,H)]
    ]
    
    for edge in edges:
        xs, ys, zs = zip(*edge)
        ax.plot(xs, ys, zs, 'k--', alpha=0.6, linewidth=1)
    
    # 绘制装入的箱子
    colors = ['red', 'blue', 'green', 'yellow', 'purple', 'orange', 'cyan', 'magenta']
    
    for i, row in enumerate(result):
        # 将类型字符串转换为数字索引
        type_index = ord(row["类型"]) - ord('A')  # A=0, B=1, C=2, D=3
        color = colors[type_index % len(colors)]
        ax.bar3d(row["X坐标"], row["Y坐标"], row["Z坐标"], 
                row["长"], row["宽"], row["高"], 
                color=color, alpha=0.7, 
                label=f'类型{row["类型"]}' if i == 0 or row["类型"] != result[i-1]["类型"] else "")
    
    ax.set_xlim([0, L])
    ax.set_ylim([0, W])
    ax.set_zlim([0, H])
    ax.set_xlabel('X (长度)')
    ax.set_ylabel('Y (宽度)')
    ax.set_zlabel('Z (高度)')
    ax.set_title('三维装箱结果可视化')
    
    # 添加图例
    handles, labels = ax.get_legend_handles_labels()
    by_label = dict(zip(labels, handles))
    ax.legend(by_label.values(), by_label.keys())
    
    plt.tight_layout()
    plt.show()
    
    print(f"\n=== 装箱统计 ===")
    print(f"装入箱子总数: {len(result)}")
    print(f"总体积利用率: {total_volume/(L*W*H)*100:.1f}%")
    
    # 按类型统计
    type_stats = {}
    for row in result:
        t = row["类型"]
        if t not in type_stats:
            type_stats[t] = {"count": 0, "volume": 0}
        type_stats[t]["count"] += 1
        type_stats[t]["volume"] += row["体积"]
    
    print("\n各类型装箱统计:")
    type_mapping = {bt["type_id"]: bt for bt in box_types_input}
    for t in sorted(type_stats.keys()):
        total_of_type = type_mapping[t]["quantity"]
        loaded_count = type_stats[t]["count"]
        print(f"  类型{t}: {loaded_count}/{total_of_type} 个被装入，"
              f"装入率: {loaded_count/total_of_type*100:.1f}%，"
              f"总体积: {type_stats[t]['volume']}")
else:
    print("没有装箱结果可以可视化")

# %%
# 检查是否已定义solve_3d_bpp函数
if 'solve_3d_bpp' not in globals():
    print("错误: solve_3d_bpp函数未定义!")
    print("请先运行第1个单元格来定义求解函数。")
    print("步骤:")
    print("1. 运行第1个单元格 (定义solve_3d_bpp函数)")
    print("2. 再运行本单元格 (用户界面)")
else:
    print("✓ solve_3d_bpp函数已定义，可以开始使用界面")

def get_user_input():
    """
    获取用户输入的集装箱尺寸和箱子信息
    
    返回:
    - container_dims: 集装箱尺寸 (L, W, H)
    - box_types: 箱子类型列表
    """
    print("=" * 50)
    print("三维装箱问题求解器")
    print("=" * 50)
    
    # 获取集装箱尺寸
    print("\n请输入集装箱尺寸:")
    while True:
        try:
            L = int(input("集装箱长度 (L): "))
            W = int(input("集装箱宽度 (W): "))
            H = int(input("集装箱高度 (H): "))
            if L > 0 and W > 0 and H > 0:
                break
            else:
                print("尺寸必须大于0，请重新输入！")
        except ValueError:
            print("请输入有效的整数！")
    
    container_dims = (L, W, H)
    print(f"集装箱尺寸: {L} x {W} x {H}")
    
    # 获取箱子类型数量
    print("\n请输入箱子类型信息:")
    while True:
        try:
            num_types = int(input("箱子类型数量: "))
            if num_types > 0:
                break
            else:
                print("类型数量必须大于0，请重新输入！")
        except ValueError:
            print("请输入有效的整数！")
    
    # 获取每种类型的箱子信息
    box_types = []
    for i in range(num_types):
        print(f"\n--- 第 {i+1} 种箱子类型 ---")
        type_id = input(f"类型名称 (如 A, B, C...): ").strip()
        if not type_id:
            type_id = chr(ord('A') + i)  # 默认使用 A, B, C...
        
        while True:
            try:
                l = int(input(f"箱子长度: "))
                w = int(input(f"箱子宽度: "))
                h = int(input(f"箱子高度: "))
                quantity = int(input(f"箱子数量: "))
                
                if l > 0 and w > 0 and h > 0 and quantity > 0:
                    break
                else:
                    print("所有数值必须大于0，请重新输入！")
            except ValueError:
                print("请输入有效的整数！")
        
        box_types.append({
            "type_id": type_id,
            "l": l,
            "w": w,
            "h": h,
            "quantity": quantity
        })
        
        volume = l * w * h
        total_volume = volume * quantity
        print(f"类型 {type_id}: {l}x{w}x{h}, 单个体积: {volume}, 数量: {quantity}, 总体积: {total_volume}")
    
    return container_dims, box_types

def get_solve_options():
    """
    获取求解选项
    
    返回:
    - time_limit: 求解时间限制
    - maximize_volume: 是否最大化体积
    """
    print("\n" + "-" * 30)
    print("求解选项设置")
    print("-" * 30)
    
    # 求解时间限制
    while True:
        try:
            time_limit = int(input("求解时间限制 (秒, 推荐60-300): "))
            if time_limit > 0:
                break
            else:
                print("时间限制必须大于0，请重新输入！")
        except ValueError:
            print("请输入有效的整数！")
    
    # 目标函数选择
    print("\n目标函数选择:")
    print("1. 最大化装入箱子数量")
    print("2. 最大化装入体积")
    
    while True:
        try:
            choice = int(input("请选择 (1 或 2): "))
            if choice == 1:
                maximize_volume = False
                print("目标: 最大化装入箱子数量")
                break
            elif choice == 2:
                maximize_volume = True
                print("目标: 最大化装入体积")
                break
            else:
                print("请输入 1 或 2！")
        except ValueError:
            print("请输入有效的数字！")
    
    return time_limit, maximize_volume

def display_results(status, results_df, solver_response, container_dims):
    """
    显示求解结果
    """
    L, W, H = container_dims
    
    print("\n" + "=" * 50)
    print("求解结果")
    print("=" * 50)
    
    if results_df is not None:
        print(f"求解状态: {'最优解' if status == 4 else '可行解'}")
        print(f"求解时间: {solver_response['solve_time']:.2f} 秒")
        print(f"目标值: {solver_response['objective_value']}")
        
        result = results_df.to_dict('records')
        total_volume = solver_response['total_volume']
        
        print(f"\n装箱汇总:")
        print(f"成功装入箱子数: {len(result)}")
        print(f"总装入体积: {total_volume}")
        print(f"容器体积: {L*W*H}")
        print(f"体积利用率: {solver_response['volume_utilization']:.1f}%")
        
        print(f"\n详细装箱结果:")
        print(results_df.to_string(index=False))
        
        return result, total_volume
    else:
        print("没有找到可行解")
        print("建议:")
        print("1. 增加求解时间限制")
        print("2. 减少箱子数量")
        print("3. 检查箱子尺寸是否合理")
        return [], 0

def main():
    """
    主函数 - 三维装箱问题求解器
    """
    # 检查solve_3d_bpp函数是否已定义
    if 'solve_3d_bpp' not in globals():
        print("错误: solve_3d_bpp函数未定义!")
        print("请先运行第1个单元格来定义求解函数，然后再运行本单元格。")
        return
    
    try:
        # 1. 获取用户输入
        container_dims, box_types = get_user_input()
        
        # 2. 获取求解选项
        time_limit, maximize_volume = get_solve_options()
        
        # 3. 显示问题摘要
        print("\n" + "-" * 30)
        print("问题摘要")
        print("-" * 30)
        L, W, H = container_dims
        print(f"集装箱尺寸: {L} x {W} x {H}")
        print(f"总体积: {L*W*H}")
        print(f"箱子类型数: {len(box_types)}")
        
        total_boxes = sum(bt['quantity'] for bt in box_types)
        total_box_volume = sum(bt['l'] * bt['w'] * bt['h'] * bt['quantity'] for bt in box_types)
        
        print(f"总箱子数: {total_boxes}")
        print(f"箱子总体积: {total_box_volume}")
        print(f"理论最大装载率: {min(100, total_box_volume//(L*W*H)*100):.1f}%")
        
        # 按体积排序
        box_types_sorted = sorted(box_types, key=lambda x: x["l"]*x["w"]*x["h"], reverse=True)
        print(f"\n箱子类型 (按体积降序):")
        for bt in box_types_sorted:
            vol = bt["l"] * bt["w"] * bt["h"]
            print(f"  {bt['type_id']}: {bt['l']}x{bt['w']}x{bt['h']} (体积:{vol}) x {bt['quantity']}个")
        
        # 4. 开始求解
        print(f"\n开始求解... (时间限制: {time_limit}秒)")
        print("=" * 50)
        
        status, results_df, solver_response = solve_3d_bpp(
            container_dims=container_dims,
            box_types=box_types,
            time_limit_seconds=time_limit,
            maximize_volume=maximize_volume
        )
        
        # 5. 显示结果
        result, total_volume = display_results(status, results_df, solver_response, container_dims)
        
        # 6. 询问是否显示可视化
        if result:
            show_viz = input("\n是否显示三维可视化图？(y/n): ").lower().strip()
            if show_viz in ['y', 'yes', '是']:
                # 设置全局变量供可视化使用
                globals()['result'] = result
                globals()['total_volume'] = total_volume
                globals()['L'] = L
                globals()['W'] = W  
                globals()['H'] = H
                globals()['box_types_input'] = box_types
                
                print("请运行下一个Cell查看三维可视化图")
        
        print(f"\n程序运行完成！结果已保存到: {os.path.abspath('装箱结果.xlsx')}")
        
    except KeyboardInterrupt:
        print("\n程序被用户中断")
    except Exception as e:
        print(f"\n程序运行出错: {e}")
        print("请检查输入是否正确")

def run_example():
    """
    运行示例数据
    """
    # 检查solve_3d_bpp函数是否已定义
    if 'solve_3d_bpp' not in globals():
        print("错误: solve_3d_bpp函数未定义!")
        print("请先运行第1个单元格来定义求解函数，然后再运行本单元格。")
        return
    
    print("使用示例数据运行...")
    
    # 示例数据
    container_dimensions = (50, 50, 50)
    box_types_input = [
        {"type_id": "A", "l": 20, "w": 10, "h": 5, "quantity": 2},
        {"type_id": "B", "l": 15, "w": 15, "h": 10, "quantity": 3},
        {"type_id": "C", "l": 10, "w": 10, "h": 10, "quantity": 1},
        {"type_id": "D", "l": 5, "w": 5, "h": 5, "quantity": 10}
    ]
    
    status, results_df, solver_response = solve_3d_bpp(
        container_dims=container_dimensions,
        box_types=box_types_input,
        time_limit_seconds=60,
        maximize_volume=False
    )
    
    result, total_volume = display_results(status, results_df, solver_response, container_dimensions)
    
    if result:
        # 设置全局变量供可视化使用
        L, W, H = container_dimensions
        globals()['result'] = result
        globals()['total_volume'] = total_volume
        globals()['L'] = L
        globals()['W'] = W  
        globals()['H'] = H
        globals()['box_types_input'] = box_types_input
        print("请运行第2个单元格查看三维可视化图")

# 主程序入口
if __name__ == "__main__":
    # 检查solve_3d_bpp函数是否已定义
    if 'solve_3d_bpp' not in globals():
        print("=" * 60)
        print("注意: 请先运行第1个单元格定义solve_3d_bpp函数！")
        print("=" * 60)
        print("使用步骤:")
        print("1. 运行第1个单元格 (定义求解函数)")
        print("2. 运行第3个单元格 (用户界面)")
        print("3. 运行第2个单元格 (查看可视化)")
    else:
        # 可以选择运行交互式输入或使用示例数据
        use_example = input("是否使用示例数据？(y/n): ").lower().strip()
        
        if use_example in ['y', 'yes', '是']:
            run_example()
        else:
            main()

# %%
# 三维装箱结果可视化
import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d import Axes3D

# 检查是否有结果数据
if 'result' in globals() and result:
    print(f"正在可视化 {len(result)} 个装入的箱子...")
    
    fig = plt.figure(figsize=(14, 10))
    ax = fig.add_subplot(111, projection='3d')
    
    # 绘制集装箱边框
    # 12条边线构成一个立方体框架
    edges = [
        [(0,0,0), (L,0,0)], [(0,0,0), (0,W,0)], [(0,0,0), (0,0,H)],        # 原点出发的三条边
        [(L,W,H), (0,W,H)], [(L,W,H), (L,0,H)], [(L,W,H), (L,W,0)],        # 对角点出发的三条边
        [(L,0,0), (L,W,0)], [(L,0,0), (L,0,H)],                             # X轴最大值点的边
        [(0,W,0), (L,W,0)], [(0,W,0), (0,W,H)],                             # Y轴最大值点的边
        [(0,0,H), (L,0,H)], [(0,0,H), (0,W,H)]                              # Z轴最大值点的边
    ]
    
    # 绘制容器边框
    for edge in edges:
        xs, ys, zs = zip(*edge)
        ax.plot(xs, ys, zs, 'k--', alpha=0.8, linewidth=2)
    
    # 定义颜色方案 - 为每种箱子类型分配不同颜色
    colors = ['red', 'blue', 'green', 'yellow', 'purple', 'orange', 'cyan', 'magenta', 'brown', 'pink']
    
    # 绘制装入的箱子
    type_legend = {}  # 用于去重图例
    
    for i, box in enumerate(result):
        # 根据箱子类型确定颜色
        type_index = ord(box["类型"]) - ord('A')  # A=0, B=1, C=2, D=3
        color = colors[type_index % len(colors)]
        
        # 绘制3D箱子
        ax.bar3d(
            box["X坐标"], box["Y坐标"], box["Z坐标"],     # 位置
            box["长"], box["宽"], box["高"],              # 尺寸
            color=color, 
            alpha=0.8, 
            edgecolor='black',
            linewidth=0.5
        )
        
        # 添加箱子标签（在箱子中心位置）
        center_x = box["X坐标"] + box["长"] / 2
        center_y = box["Y坐标"] + box["宽"] / 2
        center_z = box["Z坐标"] + box["高"] / 2
        
        # 只在箱子较大时显示标签，避免重叠
        if box["长"] * box["宽"] * box["高"] > 500:  # 体积阈值
            ax.text(center_x, center_y, center_z, 
                   f'{box["类型"]}{box["实例"]}', 
                   fontsize=8, ha='center', va='center')
        
        # 收集图例信息
        if box["类型"] not in type_legend:
            type_legend[box["类型"]] = color
    
    # 设置坐标轴
    ax.set_xlim([0, L])
    ax.set_ylim([0, W])
    ax.set_zlim([0, H])
    ax.set_xlabel('X (length)', fontsize=12)
    ax.set_ylabel('Y (width)', fontsize=12)
    ax.set_zlabel('Z (height)', fontsize=12)
    
    # 设置标题
    utilization = total_volume / (L*W*H) * 100
    ax.set_title(f'Visualization of 3D boxing results\nContainer: {L}×{W}×{H}, number of boxes loaded: {len(result)}box, Volume utilization: {utilization:.1f}%', 
                fontsize=14, pad=20)
    
    # 添加图例
    legend_elements = [plt.Rectangle((0,0),1,1, facecolor=color, alpha=0.8, label=f'Type {box_type}') 
                      for box_type, color in sorted(type_legend.items())]
    ax.legend(handles=legend_elements, loc='upper left', bbox_to_anchor=(1.05, 1))
    
    # 调整视角以便更好地观察
    ax.view_init(elev=20, azim=45)
    
    plt.tight_layout()
    plt.show()
    
    # 显示详细统计信息
    print(f"\n{'='*50}")
    print(f"装箱统计汇总")
    print(f"{'='*50}")
    print(f"容器尺寸: {L} × {W} × {H}")
    print(f"容器总体积: {L*W*H:,}")
    print(f"装入箱子总数: {len(result)}")
    print(f"装入总体积: {total_volume:,}")
    print(f"体积利用率: {utilization:.2f}%")
    
    # 按类型统计
    type_stats = {}
    for box in result:
        box_type = box["类型"]
        if box_type not in type_stats:
            type_stats[box_type] = {"count": 0, "volume": 0}
        type_stats[box_type]["count"] += 1
        type_stats[box_type]["volume"] += box["体积"]
    
    print(f"\n各类型装箱详情:")
    print(f"{'类型':<8} {'装入数量':<10} {'装入率':<10} {'总体积':<12} {'原始尺寸'}")
    print("-" * 60)
    
    # 获取原始箱子类型信息
    if 'box_types_input' in globals():
        type_mapping = {bt["type_id"]: bt for bt in box_types_input}
        
        for box_type in sorted(type_stats.keys()):
            loaded_count = type_stats[box_type]["count"]
            loaded_volume = type_stats[box_type]["volume"]
            
            if box_type in type_mapping:
                total_of_type = type_mapping[box_type]["quantity"]
                load_rate = loaded_count / total_of_type * 100
                original_size = f"{type_mapping[box_type]['l']}×{type_mapping[box_type]['w']}×{type_mapping[box_type]['h']}"
            else:
                total_of_type = loaded_count
                load_rate = 100.0
                original_size = "未知"
            
            print(f"{box_type:<8} {loaded_count}/{total_of_type:<9} {load_rate:>6.1f}%    {loaded_volume:>8}    {original_size}")
    
    print(f"\n提示: 图形窗口可以用鼠标旋转和缩放来查看不同角度")
    
else:
    print("没有找到装箱结果数据!")
    print("请确保:")
    print("1. 已经成功运行第1个单元格 (定义函数)")
    print("2. 已经成功运行第3个单元格 (求解问题)")
    print("3. 求解过程找到了可行解")
    
    # 显示当前可用的变量
    if 'result' in globals():
        print(f"result 变量存在，包含 {len(result)} 个元素")
    else:
        print("result 变量不存在")
    
    available_vars = [var for var in ['L', 'W', 'H', 'total_volume', 'box_types_input'] if var in globals()]
    if available_vars:
        print(f"可用变量: {', '.join(available_vars)}")
    else:
        print("未找到相关变量")

# %%




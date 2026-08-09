# 3D Container Loading Optimization

Experimental implementations of **3D container loading / bin packing** using classical heuristics, **Google OR-Tools CP-SAT**, and **deep reinforcement learning**.

This project started from a practical container-loading problem and gradually evolved into a small testbed for comparing different approaches to combinatorial optimization.

> **Status:** research / engineering prototype.  
> The repository contains several generations of experimental code rather than a single production-ready solver.

## Problem

Given a rectangular container and a set of rectangular boxes, determine which boxes to load, their positions, and their orientations while satisfying geometric constraints.

The current implementations mainly consider:

- axis-aligned rectangular boxes;
- container boundary constraints;
- pairwise non-overlap constraints;
- multiple box orientations;
- maximizing packed volume or the number of packed boxes.

## Implemented Approaches

### 1. Recursive / grouping heuristic in C++

`Bin_packing.cpp` is an early heuristic prototype based on:

- sorting box groups by volume;
- combining boxes of the same type into larger cuboids;
- recursive packing;
- simplified free-space decomposition;
- tracking the best solution found during the search.

This version represents an early attempt to design the packing logic directly rather than relying on an optimization library.

### 2. 3D volume-greedy heuristic in C++

`Bin_packing_3D.cpp` implements a more geometric heuristic with:

- six axis-aligned box orientations;
- explicit 3D collision detection;
- candidate placement points;
- volume-based box ordering;
- greedy placement;
- CSV export of packed coordinates.

### 3. OR-Tools CP-SAT formulation

`ortools_Bin_packing.py` and `ortool_Bin_packing.ipynb` formulate the problem with Google OR-Tools CP-SAT.

For each box instance, the model contains:

- a Boolean variable indicating whether the box is packed;
- six orientation variables;
- integer `(x, y, z)` coordinates;
- realized length, width, and height after rotation.

The model enforces:

- exactly one orientation for every selected box;
- container boundary constraints;
- pairwise 3D non-overlap through six possible relative separation relations.

The objective can be switched between:

- maximizing total packed volume;
- maximizing the number of packed boxes.

### 4. DQN reinforcement-learning prototype

`Reinforce_learning_bin_packing.ipynb` explores sequential box placement using a Deep Q-Network (DQN).

The experimental environment includes:

- a coarse 2D height-map representation of the container;
- features describing the current box;
- additional progress / utilization features;
- heuristic candidate placements;
- experience replay;
- a target network;
- epsilon-greedy exploration.

The RL implementation is exploratory and uses a different test instance from the CP-SAT experiments, so its results should **not** be compared directly with the CP-SAT numbers below.

## Example Results

### CP-SAT notebook experiment

One recorded experiment used:

- container: `1200 × 235 × 269`;
- 60 candidate boxes:
  - 10 × `200 × 150 × 120`;
  - 20 × `150 × 130 × 80`;
  - 30 × `80 × 60 × 40`;
- objective: maximize packed volume;
- time limit: 60 seconds.

The solver returned a **FEASIBLE** solution after approximately **61.87 s**:

| Metric | Result |
|---|---:|
| Boxes packed | 55 / 60 |
| Packed volume | 66,528,000 |
| Container volume | 75,858,000 |
| Volume utilization | **87.70%** |
| Solver status | FEASIBLE |

This result was not proven optimal within the time limit.

![CP-SAT packing example](assets/cp_sat_packing_example.png)

### Additional recorded loading example

An earlier experiment record contains a solution for a `1200 × 235 × 269` container with:

- **63 boxes packed**;
- **78.46% volume utilization**;
- a 60-second solver time limit.

This is retained as a historical project result rather than a standardized benchmark.

### Historical heuristic vs. CP-SAT utilization record

An earlier project record reports the following utilization values on one comparison instance:

| Method | Volume utilization |
|---|---:|
| C++ heuristic | 57.5813% |
| CP-SAT | 83.29% |

The original notes contained unreliable runtime claims for this comparison, so runtime numbers are intentionally omitted here.

### Reinforcement-learning demo

The recorded DQN demo used a different instance:

- container: `12032 × 2352 × 2698 mm`;
- 180 boxes;
- total box volume: approximately `7.92 m³`;
- container volume: approximately `76.35 m³`;
- grid resolution: `100 mm`.

Recorded training / evaluation results:

| Metric | Result |
|---|---:|
| Best training utilization | 8.58% |
| Best training boxes packed | 73 |
| Evaluation utilization | 7.48% |
| Evaluation boxes packed | 46 |
| Evaluation episodes | 3 |

Because the total volume of all available boxes is only about 10.37% of the container volume in this demo, these utilization values are not comparable to the CP-SAT experiment above.

![RL training demo](assets/rl_training_demo.png)

## Repository Contents

```text
.
├── Bin_packing.cpp
├── Bin_packing_3D.cpp
├── Bin_packing_linear.cpp
├── ortools_Bin_packing.py
├── ortool_Bin_packing.ipynb
├── Reinforce_learning_bin_packing.ipynb
├── encasement.csv
├── rl_packing_result.csv
├── 装箱结果.xlsx
├── Project.doc
└── test.py
```

The current structure is intentionally kept close to the original project workspace. It can be reorganized later as the project is cleaned up.

## Installation

For the Python implementations:

```bash
python -m pip install -r requirements.txt
```

Main dependencies:

- OR-Tools
- pandas
- NumPy
- Matplotlib
- openpyxl
- TensorFlow
- Jupyter

The large precompiled OR-Tools C++ SDK is intentionally not included in the Git repository.

## Running

### CP-SAT version

```bash
python ortools_Bin_packing.py
```

or open:

```text
ortool_Bin_packing.ipynb
```

in Jupyter.

### Reinforcement-learning version

Open:

```text
Reinforce_learning_bin_packing.ipynb
```

in Jupyter and run the cells in order.

### C++ 3D heuristic

For example, with GCC:

```bash
g++ -std=c++17 -O2 Bin_packing_3D.cpp -o bin_packing_3d
./bin_packing_3d
```

On Windows:

```cmd
g++ -std=c++17 -O2 Bin_packing_3D.cpp -o bin_packing_3d.exe
bin_packing_3d.exe
```

## Current Limitations

The project is still an early prototype. Important directions for cleanup and improvement include:

- building a unified, reproducible benchmark suite;
- improving scalability for larger numbers of boxes;
- reducing symmetry for identical boxes and repeated orientations;
- improving the free-space representation in heuristic methods;
- improving state and action representations for learning-based methods;
- separating experimental code from reusable solver code.

## Future Work

The most interesting next step is to move toward **learning-augmented combinatorial optimization**: use machine learning to guide a classical optimization or search method rather than asking a neural network to solve the complete NP-hard problem by itself.

Possible extensions include:

- symmetry breaking and stronger preprocessing;
- better exact / CP-SAT / MILP formulations;
- learning to rank candidate placements;
- learning box-ordering or branching heuristics;
- warm-starting exact solvers with heuristic or learned solutions;
- weight and payload constraints;
- center-of-gravity and stability constraints;
- stacking / support constraints;
- fragile-item and forbidden-orientation constraints;
- unloading-order constraints;
- multi-container loading;
- integration with vehicle routing and scheduling.

## Project Motivation

The project is intended as a continuing experiment at the intersection of:

**combinatorial optimization · algorithms · operations research · reinforcement learning · logistics / industrial AI**

Future versions will focus on cleaner implementations, reproducible experiments, and stronger hybrid optimization methods.

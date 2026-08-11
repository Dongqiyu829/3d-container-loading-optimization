# 3D Container Loading Optimization

Experimental implementations of **3D container loading / bin packing** using classical heuristics and **Google OR-Tools CP-SAT**, with an unfinished reinforcement-learning extension under development.

![CP-SAT packing example](assets/cp_sat_packing_example.png)

This project started from a practical container-loading problem and gradually evolved into a small testbed for exploring different approaches to combinatorial optimization.

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
- orientation variables;
- integer `(x, y, z)` coordinates;
- realized length, width, and height after rotation.

The model enforces:

- one orientation for every selected box;
- container boundary constraints;
- pairwise 3D non-overlap through relative separation constraints.

The objective can be switched between:

- maximizing total packed volume;
- maximizing the number of packed boxes.

## Work in Progress: Reinforcement Learning

`Reinforce_learning_bin_packing.ipynb` is an **unfinished exploratory notebook** for sequential box placement using reinforcement learning.

The intended design includes:

- a coarse 2D height-map representation of the container;
- features describing the current box and packing state;
- heuristic candidate placements;
- experience replay;
- a target network;
- epsilon-greedy exploration.

**This component is not yet complete and should not be treated as an implemented or benchmarked method.**  
No reinforcement-learning performance claims or comparisons are made here.

The image below is retained only as a **development visualization from the unfinished notebook**, not as evidence of a validated RL result.

![RL development visualization](assets/rl_training_demo.png)

## Recorded Results

The following numbers are retained from earlier project records. They are useful as development history, but should **not** be interpreted as a standardized benchmark suite.

### CP-SAT notebook record

One recorded CP-SAT run used:

- container: `1200 × 235 × 269`;
- 60 candidate boxes:
  - 10 × `200 × 150 × 120`;
  - 20 × `150 × 130 × 80`;
  - 30 × `80 × 60 × 40`;
- objective: maximize packed volume;
- time limit: 60 seconds.

The recorded output was:

| Metric             | Result |
| ------------------ | -----: |
| Boxes packed       | 55 / 60 |
| Packed volume      | 66,528,000 |
| Container volume   | 75,858,000 |
| Volume utilization | **87.70%** |
| Solver status      | FEASIBLE |

This was a feasible solution and was not recorded as proven optimal.

### Additional recorded loading example

Another earlier project record contains a solution for a `1200 × 235 × 269` container with:

- **63 boxes packed**;
- **78.46% volume utilization**;
- a 60-second solver time limit.

This is kept as historical project output rather than as a standardized benchmark.

### Historical heuristic vs. CP-SAT utilization record

An earlier comparison record reports:

| Method        | Volume utilization |
| ------------- | -----------------: |
| C++ heuristic | 57.5813% |
| CP-SAT        | 83.29% |

The original notes contained unreliable runtime claims for this comparison, so runtime numbers are intentionally omitted.

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
- Jupyter

Additional dependencies may be required for unfinished experimental notebooks.

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

### Reinforcement-learning notebook

The reinforcement-learning notebook is currently incomplete and is kept for ongoing development rather than as a finished runnable method.

```text
Reinforce_learning_bin_packing.ipynb
```

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
- separating experimental code from reusable solver code;
- completing and validating the learning-based component before making any RL comparisons.

## Future Work

The most interesting next step is to move toward **learning-augmented combinatorial optimization**: use machine learning to guide a classical optimization or search method rather than asking a neural network to solve the complete NP-hard problem by itself.

Possible extensions include:

- stronger exact / CP-SAT / MILP formulations;
- symmetry breaking and stronger preprocessing;
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

This repository is a continuing experiment in **combinatorial optimization and algorithm design**.

Future versions will focus on cleaner implementations, reproducible experiments, and stronger hybrid optimization methods.

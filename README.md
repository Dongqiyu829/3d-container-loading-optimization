# 3D Container Loading Optimization

Experimental implementations of **3D container loading / bin packing** using classical heuristics and **Google OR-Tools CP-SAT**.

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

The objective can be switched between maximizing total packed volume and maximizing the number of packed boxes.

## Work in Progress: Reinforcement Learning

`Reinforce_learning_bin_packing.ipynb` is an **unfinished exploratory notebook** for sequential box placement with reinforcement learning.

The intended direction includes:

- a coarse height-map representation of the container;
- features describing the current box and packing state;
- candidate placement actions;
- experience replay and a target network;
- epsilon-greedy exploration.

**This part is not yet complete and should not be treated as an implemented or benchmarked method.**

No reinforcement-learning performance claims or comparisons are made in this README.

## Recorded Result

### Historical heuristic vs. CP-SAT utilization record

An earlier project record reports the following utilization values on one comparison instance:

| Method        | Volume utilization |
| ------------- | -----------------: |
| C++ heuristic |           57.5813% |
| CP-SAT        |             83.29% |

These values are retained as a **historical project record**, not as a standardized or fully reproducible benchmark.

The original notes contained unreliable runtime claims for this comparison, so runtime numbers are intentionally omitted here.

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

## Installation

For the Python implementations:

```bash
python -m pip install -r requirements.txt
```

Main dependencies include OR-Tools, pandas, NumPy, Matplotlib, openpyxl, and Jupyter.

Additional dependencies may be required for unfinished experimental notebooks.

## Running

### CP-SAT version

```bash
python ortools_Bin_packing.py
```

or open `ortool_Bin_packing.ipynb` in Jupyter.

### Reinforcement-learning notebook

The reinforcement-learning notebook is currently incomplete and is kept for ongoing development rather than as a finished runnable method.

### C++ 3D heuristic

```bash
g++ -std=c++17 -O2 Bin_packing_3D.cpp -o bin_packing_3d
./bin_packing_3d
```

## Current Limitations

- no unified, reproducible benchmark suite yet;
- scalability remains limited for larger instances;
- symmetry reduction and preprocessing can be improved;
- heuristic free-space representation is still simple;
- experimental code has not yet been reorganized into reusable solver modules;
- the reinforcement-learning component is incomplete and has not been validated.

## Future Work

The most interesting next step is to move toward **learning-augmented combinatorial optimization**: use machine learning to guide a classical optimization or search method rather than asking a neural network to solve the complete NP-hard problem by itself.

Possible extensions include:

- stronger exact / CP-SAT / MILP formulations;
- symmetry breaking and preprocessing;
- learning to rank candidate placements;
- learning box-ordering or branching heuristics;
- warm-starting exact solvers with heuristic or learned solutions;
- weight, payload, stability, support, and unloading-order constraints;
- multi-container loading;
- integration with vehicle routing and scheduling.

## Project Motivation

This repository is a continuing experiment in **combinatorial optimization and algorithm design**. Future versions will focus on cleaner implementations, reproducible experiments, and stronger hybrid optimization methods.

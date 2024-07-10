# Holographic Entropy Cone
Database of extremal elements of the holographic entropy cone (HEC).

## Intro ##

The HEC is a family of polyhedral cones $H_n$ labelled by the number of parties $n \in \mathbb{N}$.  
Each $H_n$ can be dually described by either its facet inequalities or its extreme rays.  
A complete characterization of $H_n$ requires knowledge of both sets of extremal elements.  
This has only been accomplished for $n \leq 5$, and results for $n \geq 6$ are only partial.  


## Description ##

This repository collects all known extremal elements of $H_n$ for $n \leq 6$.  
Each $H_n$ is invariant under the symmetric group of degree $n+1$.  
Files contain one representative element per symmetry orbit.  
Elements of $H_n$ obtained as lifts from $H_k$ for $k < n$ are listed first.


## Summary ##

Orbit counts:
|  n  | facets (lifts) | rays (lifts) | status     |
| :-: | :------------: | :----------: | :--------: |
| 1   | 1 (0)          | 1 (0)        | complete   |
| 2   | 1 (0)          | 1 (1)        | complete   |
| 3   | 2 (1)          | 2 (1)        | complete   |
| 4   | 2 (2)          | 3 (2)        | complete   |
| 5   | 8 (3)          | 19 (3)       | complete   |
| 6   | 1877 (11)      | 4145 (19)    | incomplete |

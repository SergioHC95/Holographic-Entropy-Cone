# Holographic Entropy Cone (HEC) #

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


## Attribution ##

If you find this data useful for your research, please consider citing the following papers.

 * Complete description of $H_n$ for $n \leq 5$ from [arXiv:1903.09148](https://arxiv.org/abs/1903.09148):
~~~bibtex
  @article{n5hec,
      author         = "Hern\'andez Cuenca, Sergio",
      title          = "{The Holographic Entropy Cone for Five Regions}",
      eprint         = "1903.09148",
      archivePrefix  = "arXiv",
      primaryClass   = "hep-th",
      doi            = "10.1103/PhysRevD.100.026004",
      journal        = "Phys. Rev. D",
      volume         = "100",
      number         = "2",
      pages          = "026004",
      year           = "2019",
      note           = "Data available at \url{https://github.com/SergioHC95/Holographic-Entropy-Cone}"
  }
~~~


 * Partial description of $H_n$ for $n=6$ from [arXiv:2309.06296](https://arxiv.org/abs/2309.06296):
~~~bibtex
  @article{n6hec,
      author         = "Hern\'andez-Cuenca, Sergio and Hubeny, Veronika E. and Jia, Frederic",
      title          = "{Holographic Entropy Inequalities and Multipartite Entanglement}",
      eprint         = "2309.06296",
      archivePrefix  = "arXiv",
      primaryClass   = "hep-th",
      reportNumber   = "MIT-CTP/5610",
      month          = "9",
      year           = "2023",
      note           = "Data available at \url{https://github.com/SergioHC95/Holographic-Entropy-Cone}"
  }
~~~


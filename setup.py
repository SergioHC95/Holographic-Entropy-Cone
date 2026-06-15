from __future__ import annotations

import os
import re
from pathlib import Path

import numpy as np
from Cython.Build import cythonize
from setuptools import Extension, setup
from setuptools.command.build_ext import build_ext

CYTHON_METADATA_RE = re.compile(
    r"/\* BEGIN: Cython Metadata\n.*?\nEND: Cython Metadata \*/\n\n",
    re.DOTALL,
)


class OptimizedBuildExt(build_ext):
    def build_extensions(self) -> None:
        compiler_type = self.compiler.compiler_type
        if compiler_type == "msvc":
            compile_args = ["/O2"]
            link_args = []
        else:
            compile_args = ["-O3", "-ffast-math", "-funroll-loops"]
            link_args = []
            if os.environ.get("HEC_ENABLE_LTO") == "1":
                compile_args.append("-flto")
                link_args.append("-flto")

        for extension in self.extensions:
            extension.extra_compile_args = compile_args
            extension.extra_link_args = link_args
            for source in extension.sources:
                if source.endswith(".c"):
                    path = Path(source)
                    if path.exists():
                        path.write_text(CYTHON_METADATA_RE.sub("", path.read_text()))
        super().build_extensions()


setup(
    ext_modules=cythonize(
        [
            Extension(
                f"hec.{name}",
                [f"src/hec/{name}.pyx"],
                include_dirs=[np.get_include()],
            )
            for name in ("clause_builder", "clause_direct")
        ],
        compiler_directives={
            "boundscheck": False,
            "wraparound": False,
            "cdivision": True,
            "language_level": 3,
        },
    ),
    cmdclass={"build_ext": OptimizedBuildExt},
)

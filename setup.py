from setuptools import setup, find_packages

setup(
    name="hermes-mirror",
    version="1.0.0",
    description="Sub-Agent Mirroring in One Click — snapshot, sanitize, package, and deploy clones of your Hermes Agent",
    author="Antonov Salvarrey (@asalvarrey)",
    license="MIT",
    packages=find_packages(),
    install_requires=[
        "pyyaml>=6.0",
    ],
    extras_require={
        "docker": ["docker>=6.0"],
        "all": ["docker>=6.0"],
    },
    python_requires=">=3.10",
    entry_points={
        "hermes.plugins": [
            "hermes-mirror = __init__:MirrorPlugin",
        ],
    },
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Topic :: Software Development :: Build Tools",
    ],
)

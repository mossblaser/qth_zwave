from setuptools import setup, find_packages

with open("qth_zwave/version.py", "r") as f:
    exec(f.read())

setup(
    name="qth_zwave",
    version=__version__,
    packages=find_packages(),

    # Metadata for PyPi
    url="https://github.com/mossblaser/qth_zwave",
    author="Jonathan Heathcote",
    description="A Qth interface to OpenZWave.",
    license="GPLv2",
    classifiers=[
        "Development Status :: 3 - Alpha",

        "Intended Audience :: Developers",

        "License :: OSI Approved :: GNU General Public License v2 (GPLv2)",

        "Operating System :: POSIX :: Linux",
        "Operating System :: Microsoft :: Windows",
        "Operating System :: MacOS",

        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.4",
        "Programming Language :: Python :: 3.5",
    ],
    keywords="mqtt asyncio qth home-automation zwave bridge openzwave",

    # Requirements
    install_requires=["qth>=0.6.0", "PyDispatcher>=2.0.5", "python_openzwave"],
    
    # Scripts
    entry_points={
        "console_scripts": [
            "qth_zwave = qth_zwave:main",
        ],
    }
)

from setuptools import setup, find_packages

setup(
    name="deepseek-code",
    version="4.0.0",
    packages=find_packages(where="src"),
    package_dir={"": "src"},
    entry_points={
        "console_scripts": [
            "deepseek-code=cli.main:main",
        ],
    },
    install_requires=[
        "openai>=1.0.0",
        "aiofiles>=23.0.0",
        "fastapi>=0.104.0",
        "uvicorn>=0.24.0",
        "websockets>=12.0",
        "pydantic>=2.0.0",
        "rich>=14.0.0",
        "structlog>=24.0.0",
        "python-multipart>=0.0.6",
    ],
    python_requires=">=3.10",
)
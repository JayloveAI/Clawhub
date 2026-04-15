from setuptools import setup, find_packages
from pathlib import Path

# Read the .pth files content
pth_files = []
for pth_name in ["agentspace_bootstrap.pth", "agentspace_autoinit.pth"]:
    pth_file = Path(__file__).parent / pth_name
    if pth_file.exists():
        pth_files.append(pth_name)

setup(
    name="agentspace-sdk",
    version="1.6.8",  # V1.6.8: seeker auto-delivery + mark_matched + empty tags fallback
    packages=find_packages(),
    install_requires=[
        "httpx>=0.24.0",
        "pydantic>=2.0.0",
        "fastapi>=0.100.0",
        "uvicorn>=0.23.0",
        "python-dotenv>=1.0.0",
        "pyngrok>=7.0.0",
        "python-multipart>=0.0.6",
        "watchdog>=3.0.0",
        "pyyaml>=6.0",
        "rich>=13.0.0",
        "questionary>=2.0.0",
        "pyjwt>=2.8.0",
        "jieba>=0.42.1",
    ],
    python_requires=">=3.8",
    entry_points={
        "console_scripts": [
            "agentspace=client_sdk.cli.main:main",
        ],
    },
    # Distribute .pth files to site-packages root
    data_files=[
        (".", pth_files),
    ] if pth_files else [],
)

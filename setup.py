import os
from setuptools import setup, find_packages

readme_path = os.path.join(os.path.dirname(__file__), "README.md")
long_description = ""
if os.path.exists(readme_path):
    with open(readme_path, "r", encoding="utf-8") as f:
        long_description = f.read()

setup(
    name="media_server",
    version="0.2.0",
    author="AI Agent",
    description="A high-performance media server and responsive photo gallery.",
    long_description=long_description,
    long_description_content_type="text/markdown",
    packages=find_packages(exclude=["tests*"]),
    install_requires=[
        "absl-py>=2.0.0",
        "requests>=2.28.0",
        "Pillow>=10.0.0",
        "Flask>=3.0.0",
        "Werkzeug>=3.0.0",
        "pillow-heif>=0.14.0",
        "piexif>=1.1.3",
    ],
    extras_require={
        "ml": [
            "keras>=3.0.0",
            "torch>=2.0.0",
            "torchvision>=0.15.0",
        ],
        "cloud": [
            "boto3>=1.28.0",
            "google-cloud-storage>=2.10.0",
        ],
        "dev": [
            "pytest>=8.0.0",
            "pytest-cov>=4.0.0",
            "flake8>=6.0.0",
            "black>=24.0.0",
        ],
    },
    entry_points={
        "console_scripts": [
            "media-server=media_server.server:main_flask",
        ],
    },
    python_requires=">=3.10",
)

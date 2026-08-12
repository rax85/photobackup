from setuptools import setup, find_packages

setup(
    name="media_server",
    version="0.2.0",
    author="AI Agent",
    description="A high-performance media server and responsive photo gallery.",
    long_description=open("README.md").read() if open("README.md") else "",
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

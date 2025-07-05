from setuptools import setup, find_packages

setup(
    name="rest_file_server",
    version="0.1.0",
    author="Jules",
    author_email="jules@example.com",
    description="A simple HTTP REST server to list file SHA256s in a directory.",
    long_description=open('README.md').read(),
    long_description_content_type="text/markdown",
    url="http://localhost/", # Replace with actual URL if available
    packages=find_packages(exclude=['tests*']),
    install_requires=[
        "absl-py>=1.0.0", # Specify a version range if necessary
        "requests", # For tests, but good to list if used by any utility scripts eventually
        "python-magic>=0.4.27", # For MIME type detection
    ],
    classifiers=[
        "Development Status :: 3 - Alpha",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: MIT License", # Choose an appropriate license
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.7",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Operating System :: OS Independent",
    ],
    python_requires='>=3.7',
    entry_points={
        'console_scripts': [
            'rest-file-server=rest_server.main:main_wrapper',
        ],
    },
    include_package_data=True, # If you have non-code files in your packages
)

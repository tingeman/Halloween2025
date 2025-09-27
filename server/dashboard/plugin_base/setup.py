from setuptools import setup, find_packages

setup(
    name="plugin-base",
    version="0.1.0",
    description="Standalone plugin-base helpers for the Halloween dashboard",
    packages=find_packages(),
    include_package_data=True,
    zip_safe=False,
)

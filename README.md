# TUF-In-toto Example
This is an example of using [TUF](https://github.com/theupdateframework/python-tuf) to bootstrap and distribute in-toto metadata.  
This example is an extension of the [PR#444](https://github.com/in-toto/in-toto/pull/444)

This example implements the following actions:
- TUF Repository Infrastructure initialization
- Client Infrastructure initialization
- Download target files from TUF Repository

### TUF Repository Infrastructure initialization
Run the following command to generate repo metadata. The targets file are `root.layout` and `alice.pub`. The root layout file is generated using the in-toto layout web tool and signed by the alice's key. These files are copied from [PR#444](https://github.com/in-toto/in-toto/pull/444).
```console
   $ python repo_generate/basic_repo.py
```

### Run the repository
Run the repository using the Python3 built-in HTTP module, and keep this session running.
```console
   $ python3 -m http.server -d repo_example
   Serving HTTP on :: port 8000 (http://[::]:8000/) ...
```

### Download target files from TUF Repository
```console
$ cd client_example
$ ./client_example.py download root.layout
$ ./client_example.py download alice.pub
```

# Type annotations
## PEP 484

```python
def f(x):
    # type: (int) -> str
    return "x"

a = b  # type: List[int]  
```
Works but all types should be imported

## Sphinx style

```python
def f(x):
    """
    :param int x:
    """
    return None
```
Works but only single word types

```python
def f(x):
    """
    :type x: typing.List[int]
    """
    return None
```
Works and `foo.bar.baz` modules are imported.

# Git workflow
We want `git push` command to upload tags, so that CI system can trigger release build
```
git config --global push.followTags true
```

## Subtrees

Pull or push docker image changes upstream
```
git subtree push -P docker git@github.com:technic/e2xvfb.git master
```

# Docker

run test
```
docker run --rm -v "$(pwd):/work" -e DESTDIR=/tmp/build technic93/e2xvfb python update-test.py
```

run build
```
docker run --rm -v "$(pwd):/work" -e DESTDIR=/tmp/build technic93/e2xvfb make
```

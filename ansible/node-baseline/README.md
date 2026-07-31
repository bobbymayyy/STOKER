# node-baseline

Safe initial baseline for enrolled Debian-family nodes. It verifies connectivity,
installs controller prerequisites, and creates the managed-node state directory.

```sh
sudo stoker-node-enroll node01 192.168.88.101 --user stoker
stoker project run node-baseline deploy --inventory discovered --limit node01
```

# confparser

This Python module parses a block style document into a dict using dissectors. The main goal is to parse Cisco configuration files, but any vendor is supported as long as the configuration format is block style. The dissector uses indentation or end-of-block markers to determine the hierarchical level of each line.

## Overview

A dissector is a YAML formatted nested list of dicts with any of these keys:

| Key | Description |
| --- | --- |
| match | A regular expression to match at the beginning of a line. The first unnamed capture group can be used as key or as value. Named capture groups can be used to match more than one group. |
| search | Scan through a line to find a match. |
| child | A nested dissector for a child block. The first unnamed capture group is used as key and the parsed child block as value. The named groups become key values of the child block. |
| name | Specifies the key name. If omitted, the first capture group or whole match is used as a key. Not to be used if only named groups are used. |
| value | Specifies the value in case no capture groups are used. Only valid when 'name' is used. |
| parent | Forces insertion of a parent dict using specified key. |
| key | Force capture group with specified index as key or generate unique key by setting to uuid. |
| action | Perform specified action on first capture group. Not valid when 'child' is used. |
| actionall | Perform specified action on all named capture groups. |

Supported actions are:

| Value | Description |
| --- | --- |
| expand | Convert number ranges with hyphens and commas into list of numbers |
| expand_f | Convert Foundry-style port ranges into list of ports |
| expand_h | Convert Huawei-style port ranges into list of ports |
| split | Split string into list of words |
| list | Convert string to list unconditionally |
| cidr | Convert netmask to prefix length in IP address string |
| bool | Sets the value to False if the line starts with 'no' or else to True |

Existing values are not overwritten but will be extended as lists.

Default parameters allow parsing of most configuration files, these are examples of exceptions:

| Dialect | Parameters |
| --- | --- |
| NXOS | indent=2 |
| VSP | indent=0, eob='exit' |

The dissector returns a Tree object which is a nested dict with a parser property that references the dissector used. A dissector can be created from a string or a file and can parse an iterable or a file. Multiple dissectors can be registered to the AutoDissector which uses hints to match a dissector to a file. A hint is a regular expression that is unique to the first 15 lines of a file.

## Module contents

`confparser.Dissector(stream, name=None)`
Return a new Dissector object that takes a YAML formatted dissector to parse block style documents. An open file or string object is accepted. The dissector can be optionally named using the *name* parameter.

`confparser.Dissector.from_file(filename, name=None)`
Alternate constructor that loads a dissector from the specified file.

`confparser.Dissector.parse(lines, indent=1, eob=None)`
Return a new Tree object that contains the parsed document from iterable *lines*. The number of spaces for an indent is specified by the parameter *indent*. If a document doesn't use indentation, an end-of-block marker string can be specified.

`confparser.Dissector.parse_str(string, indent=1, eob=None)`
Return a new Tree object that contains the parsed string *string*.

`confparser.Dissector.parse_file(filepath, indent=1, eob=None)`
Return a new Tree object that contains the parsed file *filepath* contents.

`confparser.AutoDissector(raise_no_match=True)`
Return a new AutoDissector object that handles automatic selection of parsers based on hints. Set *raise_no_match* to False to prevent *AutoDissector.from_file* from raising ValueError when no matching parser is found.

`confparser.AutoDissector.register(dissector, hint, **kwarg)`
Register Dissector object with hint regex and parser keyword arguments.

`confparser.AutoDissector.register_map(dissector, function, hint, **kwarg)`
Register Dissector object with hint regex and parser keyword arguments with function to apply to the parser iteratable, like the [map()](https://docs.python.org/3/library/functions.html#map) built-in function.

`confparser.AutoDissector.from_file(filename)`
Return a new Tree object from matching parser for specified file *filename*. Raises *ValueError* when no matching parser is found.

`confparser.Tree(parent=None)`
Subclass of *dict*. Return a new Tree object.

`confparser.Tree.merge_retain(other)`
Update Tree with dict *other* and concatenate values in lists of existing keys.

## Usage

Basic usage of the module:

```python
import confparser

doc = '''
- match: interface (\S+)
  parent: interface
  child:
  - match: ip address (.*)
    name: ipv4
    action: cidr
  - match: standby (\d+) ip (?P<ip>\S+)
    parent: standby
  - match: switchport trunk allowed vlan (\S+)
    name: allowed_vlan
    action: expand
'''
cfg = '''
interface GigabitEthernet1/1/1
 switchport trunk allowed vlan 10-12,15
!
interface Vlan10
 ip address 10.10.10.2 255.255.255.0
 standby 10 ip 10.10.10.1
!
'''
print(confparser.Dissector(doc).parse_str(cfg))
```

Output:

```
{
    "interface": {
        "GigabitEthernet1/1/1": {
            "allowed_vlan": [
                "10",
                "11",
                "12",
                "15"
            ]
        },
        "Vlan10": {
            "ipv4": "10.10.10.2/24",
            "standby": {
                "10": {
                    "ip": "10.10.10.1"
                }
            }
        }
    }
}
```

## Advanced usage

The dissector can also be easily loaded from a file and a configuration file can be parsed directly without opening a file:

```python
import confparser

dissector = confparser.Dissector.from_file('ios.yaml')
print(dissector.parse_file('config.txt'))
```

The following example loads multiple dissectors from file and registers them to the AutoDissector with regex hints. All text files in the current directory are parsed using all available processor cores and the result is written to a JSON formatted file. Note that Python 3.3+ is required to use Pool.map with instance methods.

```python
import confparser
import multiprocessing
import glob
import json

if __name__ == '__main__':
    auto = confparser.AutoDissector()
    auto.register(confparser.Dissector.from_file('ios.yaml'), 'version \d+.\d+$')
    auto.register(confparser.Dissector.from_file('nxos.yaml'), 'version \d+.\d+\(\d+\)', indent=2)
    auto.register(confparser.Dissector.from_file('iosxr.yaml'), '!! IOS XR Configuration')
    pool = multiprocessing.Pool()
    result = pool.map(auto.from_file, glob.glob('*.txt'), 1)
    with open('output.json', 'w') as f:
        json.dump({tree.source:tree for tree in result if tree}, f, indent=4)
```

The AutoDissector sets *Tree.source* to the filename of the parsed file and is used as key in the dictionary comprehention.

## Installation

Make sure you have [Python](https://www.python.org/) 2.7+ or 3.2+ installed on your system. Install [ipaddress](https://pypi.org/project/ipaddress/) if you are using a 2.7 or 3.2 version. Install [PyYAML](https://pypi.org/project/PyYAML/) using [PIP](https://pypi.org/project/pip/) on Linux or macOS:

`pip install pyyaml`

or on Windows as follows:

`python -m pip install pyyaml`

or on Ubuntu as follows:

`sudo apt-get install python-yaml`

Just copy directory *confparser* to your machine.

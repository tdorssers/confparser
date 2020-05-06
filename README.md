# confparser

This Python module parses a block style document into a dict using dissectors. The main goal is to parse Cisco configuration files.

## Overview

A dissector is a nested list of dicts formatted in YAML:

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
| split | Split string into list of words |
| list | Convert string to list unconditionally |
| cidr | Convert netmask to prefix length in IP address string |
| bool | Sets the value to False if the line starts with 'no' or else to True |

Existing values are not overwritten but will be extended as lists.

Default parameters allow parsing of most configuration files. 

To parse NXOS use indent=2

To parse VSP use indent=0, eob='exit'

## Usage

Basic usage of the module:

```python
import confparser

doc = '''
- match: vlan (\S+)
  parent: vlan
  action: expand
  child:
    match: name (?P<name>\S+)
- match: interface (\S+)
  parent: interface
  child:
  - match: vrf forwarding (?P<vrf>\S+)
  - match: ip address (.*)
    name: ipv4
    action: cidr
  - match: shutdown
    name: admin_state
  - match: no cdp enable
    name: cdp
    value: disable
  - match: switchport trunk allowed vlan (\S+)
    name: allowed_vlan
    action: expand
- match: router bgp (?P<local_as>\d+)
  name: bgp
  child:
  - match: bgp router-id (?P<router_id>\S+)
  - match: neighbor (\S+) remote-as (?P<remote_as>.*)
    parent: neighbor'''
cfg = '''
vlan 10-12
!
vlan 15
 name test
!
interface GigabitEthernet1/1/1
 switchport trunk allowed vlan 10-12,15
 shutdown
 no cdp enable
!
interface Vlan10
 vrf forwarding test
 ip address 10.10.10.2 255.255.255.0
!
router bgp 65000
 bgp router-id 10.0.0.1
 neighbor 10.10.10.10 remote-as 65001
'''
dissector = confparser.Dissector(doc)
print(dissector.parse(iter(cfg.splitlines())))
```

Output:

```
{
    "vlan": {
        "10": {},
        "11": {},
        "12": {},
        "15": {
            "name": "test"
        }
    },
    "interface": {
        "GigabitEthernet1/1/1": {
            "allowed_vlan": [
                "10",
                "11",
                "12",
                "15"
            ],
            "admin_state": "shutdown",
            "cdp": "disable"
        },
        "Vlan10": {
            "vrf": "test",
            "ipv4": "10.10.10.2/24"
        }
    },
    "bgp": {
        "local_as": "65000",
        "router_id": "10.0.0.1",
        "neighbor": {
            "10.10.10.10": {
                "remote_as": "65001"
            }
        }
    }
}
```

## Installation

Make sure you have [Python](https://www.python.org/) 2.7+ or 3.2+ installed on your system. Install [ipaddress](https://pypi.org/project/ipaddress/) if you have 2.7 or 3.2 installed. Install [PyYAML](https://pypi.org/project/PyYAML/) using [PIP](https://pypi.org/project/pip/) on Linux or macOS:

`pip install pyyaml`

or on Windows as follows:

`python -m pip install pyyaml`

or on Ubuntu as follows:

`sudo apt-get install python-yaml`

Copy directory *confparser* to your machine.

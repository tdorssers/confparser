"""
Parse a block style document, such as Cisco configuration files, into a JSON
formattable structure using dissectors.

A dissector is a YAML formatted nested list of dicts with any of these keys:
match    : A regular expression to match at the beginning of a line. The first
           unnamed capture group can be used as key or as value. Named capture
           groups can be used to match more than one group.
search   : Scan through a line to find a match.
child    : A nested dissector for a child block. The first unnamed capture group
           is used as key and the parsed child block as value. The named groups
           become key values of the child block.
name     : Specifies the key name. If omitted, the first capture group or whole
           match is used as a key. Not to be used if only named groups are used.
value    : Specifies the value. Not to be used if only named groups are used.
parent   : Forces insertion of a parent dict using specified key.
grouping : Consider all named groups as a single branch. Not valid when 'child',
           'name' or 'value' are used.
key      : Index of unnamed group as root of tree of unnamed groups. Named
           capture groups are added as leaves. 'action' is applied to the root.
           'actionall' is applied to other groups. 'child', 'name', 'value' and
           'grouping' are ignored.
action   : Perform specified action on first unnamed capture group or on whole
           match if no capture group specified. Not valid when 'child' is used.
actionall: Perform specified action on all named capture groups.

Supported actions are:
expand   : Convert number ranges with hyphens and commas into list of numbers
expand_f : Convert Foundry-style port ranges into list of ports
expand_h : Convert Huawei-style port ranges into list of ports
split    : Split string into list of words
list     : Convert string to list unconditionally
cidr     : Convert netmask to prefix length in IP address string
cidr_l   : Convert string to CIDR format and then to list unconditionally
bool     : Sets the value to False if the line starts with 'no' or else to True
decrypt7 : Decrypts a Cisco type 7 password

Supported groupings are:
implicit : Create list of branches when key is duplicate.
explicit : Create list of branches unconditionally.

Existing values are not overwritten but will be extended as lists.

Default parameters allow parsing of most configuration files.
To parse NXOS use indent=2
To parse VSP use indent=0, eob='exit'

The Dissector class returns a Tree object which is a nested dict with attributes
that reference the dissector and source file used. A dissector can be created
from a string or a file and can parse an iterable, a string or a file. Multiple
dissectors can be registered to the AutoDissector which uses hints to match a
dissector to a file. A hint is a regular expression that is unique to the first
23 lines of a file.
"""

# Author: Tim Dorssers

import re
import json
import itertools
import ipaddress
import yaml


class Tree(dict):
    """ Autovivificious dictionary with parent property as tree stucture """

    __slots__ = 'parent', 'parser', 'source'

    def __init__(self, parent=None):
        """ Initialize self """
        self.parent = parent
        if parent is None:
            self.parser = None
            self.source = None

    def __missing__(self, key):
        """ Implement self[key] when key is not in the dictionary """
        value = self[key] = type(self)(self)
        return value

    def __str__(self):
        """ Serialize dictionary to JSON formatted string with indents """
        return json.dumps(self, indent=4)

    def merge_retain(self, other):
        """ Update dict with other and concatenate values of existing keys """
        for key in other.keys():
            if key in self:
                # Make sure value is a list
                v = other[key] if isinstance(other[key], list) else [other[key]]
                if isinstance(self[key], list):
                    self[key] += v  # Append value to list
                else:
                    self[key] = [self[key]] + v  # Make list and append value
            else:
                self[key] = other[key]


class Dissector(object):
    """ Takes a YAML formatted dissector to parse block style documents """

    def __init__(self, stream, name=None):
        """ Initialize self """
        self.name = name  # Optional name of dissector
        self.context = yaml.safe_load(stream)
        self._compile_dissector(self.context)

    def _compile_dissector(self, context):
        """ Compile regular expressions in dissector """
        context = [context] if not isinstance(context, list) else context
        for item in context:
            if 'match' in item:
                item['prog'] = re.compile(item['match'])
            elif 'search' in item:
                item['prog'] = re.compile(item['search'])
            else:
                raise KeyError("Missing 'match' or 'search' key")
            # Parse child using recursion
            if 'child' in item:
                self._compile_dissector(item['child'])

    @classmethod
    def from_file(cls, filename, **kwargs):
        """ Alternate constructor that loads a dissector from file """
        with open(filename) as f:
            buf = f.read()
        return cls(buf, **kwargs)

    def parse(self, lines, **kwargs):
        """ Return a Tree object that contains the parsed iterable """
        tree = _parse(lines, self.context, **kwargs)
        tree.parser = self  # Store reference of used dissector
        return tree

    def parse_str(self, string, **kwargs):
        """ Return a Tree object that contains the parsed string """
        tree = _parse(iter(string.splitlines()), self.context, **kwargs)
        tree.parser = self
        return tree

    def parse_file(self, filepath, **kwargs):
        """ Return a Tree object that contains the parsed file contents """
        with open(filepath) as f:
            tree = _parse(f, self.context, **kwargs)
            tree.parser = self
            return tree

class AutoDissector(object):
    """ Handles automatic selection of parsers based on hints """

    def __init__(self, raise_no_match=True):
        """ Initialize self """
        self.parsers = {}
        self.raise_no_match = raise_no_match

    def register(self, dissector, hint, **kwargs):
        """ Register dissector object with hint regex and parser arguments """
        if not isinstance(dissector, Dissector):
            raise TypeError('Expected a dissector object')
        self.parsers[dissector] = {'hint': re.compile(hint), 'kwargs': kwargs}

    def register_map(self, dissector, function, hint, **kwargs):
        """ Register with function to apply to the parser iteratable """
        self.register(dissector, hint, **kwargs)
        self.parsers[dissector]['function'] = function

    def from_file(self, filename):
        """ Return Tree object from matching parser for given file """
        with open(filename) as f:
            # Look for hint in first few lines of the file
            for line in itertools.islice(f, 23):
                for parser, param in self.parsers.items():
                    if param['hint'].search(line):
                        f.seek(0)
                        if 'function' in param:
                            # Apply function to iterable f
                            tree = parser.parse(param['function'](f),
                                                **param['kwargs'])
                        else:
                            tree = parser.parse(f, **param['kwargs'])
                        tree.source = filename  # Save source filename
                        return tree
        if self.raise_no_match:
            raise ValueError('None of the hints matched file %s' % filename)
        return None

    def from_str(self, string):
        """ Return Tree object from matching parser for given string """
        # Look for hint in first few lines of the string
        for match in itertools.islice(re.finditer(r'.*', string), 23):
            for parser, param in self.parsers.items():
                if param['hint'].search(match.group()):
                    lines = iter(string.splitlines())
                    if 'function' in param:
                        # Apply function to iterable f
                        tree = parser.parse(param['function'](lines),
                                            **param['kwargs'])
                    else:
                        tree = parser.parse(lines, **param['kwargs'])
                    return tree
        if self.raise_no_match:
            raise ValueError('None of the hints matched')
        return None


def _parse(lines, context, indent=1, eob=None, eof='end'):
    """ Parse block style document through given nested dict of dissectors """
    result = Tree()
    # Push root reference to stack
    r_stack = [result]
    c_stack = [context]
    level = 0
    while True:
        # Jump out when the iterator runs out of lines
        line = next(lines, None)
        if line is None:
            break
        # Also jump out when end of file marker is seen
        line = line.rstrip()
        if line == eof:
            break
        # Pop branch reference of stack if not enough indentation
        while level and not line.startswith(' ' * indent * level):
            level -= 1
            c_stack.pop()
            r_stack.pop()
        # Pop stack when end of block marker is seen
        if eob and level and line.strip() == eob:
            level -= 1
            c_stack.pop()
            r_stack.pop()
        # Last item on stack is the current dissector, which should be a list
        if not isinstance(c_stack[-1], list):
            c_stack[-1] = [c_stack[-1]]
        # Iterate over list of dissectors
        for item in c_stack[-1]:
            if 'match' in item:
                m = item['prog'].match(line[indent * level:])
            else:
                m = item['prog'].search(line[indent * level:])
            # Skip if regular expression does not match
            if not m:
                continue
            # Apply specified action to found named capturing group values
            named_groups = {k: _action(item.get('actionall'), v)
                            for k, v in m.groupdict().items() if v is not None}
            if 'parent' in item:
                # Insert specified parent Tree object and retain reference
                p_result = r_stack[-1][item['parent']]
            else:
                p_result = r_stack[-1]
            if 'key' in item:
                # Use specified unnamed group as root in nested dict
                tree = named_groups
                for idx in range(m.re.groups, 0, -1):
                    if idx in m.re.groupindex.values() or idx == item['key']:
                        continue
                    key = _action(item.get('actionall'), m.group(idx))
                    key = [key] if not isinstance(key, list) else key
                    # Last unnamed group as value and others as nested dict
                    tree = {k: tree for k in key} if tree else key[0]
                # Apply specified action to root and add to Tree
                key = _action(item.get('action'), m.group(item['key']))
                for k in [key] if not isinstance(key, list) else key:
                    if isinstance(tree, dict):
                        p_result[k].merge_retain(tree)
                    else:
                        # Add single value to Tree
                        if k in p_result and isinstance(p_result[k], Tree):
                            p_result[k].merge_retain({tree: {}})
                        else:
                            p_result.merge_retain({k: tree})
                continue
            # Use whole match as key if no groups match
            key = m.group(0) if not m.lastindex else None
            if m.re.groups > len(m.re.groupindex):
                # An unnamed group exists, use first unnamed group as key
                key = m.group(next(x for x in itertools.count(1)
                                   if x not in m.re.groupindex.values()))
            if 'child' in item:
                # Override key by name if specified and apply group action
                key = _action(item.get('action'), item.get('name', key))
                key = [key] if not isinstance(key, list) else key
                # Push branch reference to stack
                r_stack.append(p_result[key[0]])
                c_stack.append(item['child'])
                level += 1
                # Add to Tree using named groups as value
                p_result[key[0]].merge_retain(named_groups)
                # Make references to first stacked key in case of multiple keys
                for k in key[1:]:
                    p_result[k] = p_result[key[0]]
            elif 'name' in item:
                # Use 'key' as value or specified value and apply group action
                value = _action(item.get('action'), item.get('value', key))
                # Add the unnamed group and named groups
                named_groups.update({item['name']: value})
                p_result.merge_retain(named_groups)
            elif 'value' in item:
                # Apply action to key, use specified value for 'key' add groups
                key = _action(item.get('action'), key)
                for k in [key] if not isinstance(key, list) else key:
                    named_groups.update({k: item['value']})
                p_result.merge_retain(named_groups)
            elif key:
                # Apply specified action to key and iterate over list of keys
                key = _action(item.get('action'), key)
                for k in [key] if not isinstance(key, list) else key:
                    if item.get('grouping') == 'implicit':
                        # Add names groups to Tree as a single value
                        p_result.merge_retain({k: named_groups})
                    elif item.get('grouping') == 'explicit':
                        # Create list of named groups as value
                        p_result[k] = p_result.get(k, []) + [named_groups]
                    else:
                        # Add to Tree using named groups as value
                        p_result[k].merge_retain(named_groups)
            else:
                p_result.merge_retain(named_groups)
    return result

def _action(method, value):
    """ Run given method on value """
    if method is None or value is None:
        return value
    if method == 'expand':
        return _expand(value)
    if method == 'split':
        return value.split()
    if method == 'list':
        return [value]
    if method == 'cidr':
        return _cidr(value)
    if method == 'cidr_l':
        return [_cidr(value)]
    if method == 'expand_f':
        return _expand_f(value)
    if method == 'decrypt7':
        return _decrypt7(value)
    if method == 'bool':
        return not value.startswith('no ')
    if method == 'expand_h':
        return _expand_h(value)
    return value

def _expand(string):
    """ Convert number ranges with hyphens and commas into list of numbers """
    result = []
    for element in re.split(', *', string):
        # Expand 1-2 to [1, 2] or 1/3-4 to [1/3, 1/4] or 1/5-1/6 to [1/5, 1/6]
        m = re.match(r'([A-Za-z0-9/]*?)(\d+)\s*-\s*\1?(\d+)', element)
        if m:
            for num in range(int(m.group(2)), int(m.group(3)) + 1):
                result.append(m.group(1) + str(num))
        else:
            result.append(element.strip())
    return result

def _expand_f(string):
    """ Convert Foundry-style port ranges into list of ports """
    result = []
    for port_range in re.findall(r'ethe(?:rnet)? (\S+(?: to )?\S+)', string):
        m = re.match(r'(\S+\/)(\d+) to \S+\/(\d+)', port_range)
        if m:
            for port in range(int(m.group(2)), int(m.group(3)) + 1):
                result.append(m.group(1) + str(port))
        else:
            result.append(port_range)  # single port
    return result

def _expand_h(string):
    """ Convert Huawei-style port ranges into list of ports """
    result = []
    for element in re.split('(?<!to) (?!to)', string):
        m = re.match(r'(\d+) to (\d+)', element)
        if m:
            for num in range(int(m.group(1)), int(m.group(2)) + 1):
                result.append(str(num))
        else:
            result.append(element)
    return result

def _cidr(string):
    """ Convert netmask to prefix length in IP address string """
    try:
        return ipaddress.ip_interface(string.replace(' ', '/')).with_prefixlen
    except ValueError:
        return string

def _decrypt7(string):
    """ Decrypt cisco type 7 passwords """
    m = re.search('(^[0-9A-Fa-f]{2})([0-9A-Fa-f]+)', string)
    if not m:
        return string
    # First 2 digits are the salt index and the rest is the encrypted password
    index, enc_pw = int(m.group(1)), m.group(2)
    salt = 'dsfd;kfoA,.iyewrkldJKDHSUBsgvca69834ncxv9873254k;fg87'
    cleartext = []
    for pos in range(0, len(enc_pw), 2):
        # XOR the salt with encrypted char
        cleartext += chr(ord(salt[index]) ^ int(enc_pw[pos:pos + 2], 16))
        index = (index + 1) % 53
    return ''.join(cleartext)

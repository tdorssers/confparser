"""
Parse a block style document into a dict using dissectors

A dissector is a nested list of dicts with any of these keys: 
match    : A regular expression to match at the beginning of a line. The first
           unnamed capture group can be used as key or as value. Named capture
           groups can be used to match more than one group.
search   : Scan through a line to find a match.
child    : A nested dissector for a child block. The first unnamed capture group
           is used as key and the parsed child block as value. The named groups
           become key values of the child block.
name     : Specifies the key name. If omitted, the first capture group or whole
           match is used as a key. Not to be used if only named groups are used.
value    : Specifies the value in case no capture groups are used. Only valid
           when 'name' is used.
parent   : Forces insertion of a parent dict using specified key.
key      : Force capture group with specified index as key or generate unique
           key by setting to uuid.
action   : Perform specified action on first capture group. Not valid when
           'child' is used.
actionall: Perform specified action on all named capture groups.

Supported actions are:
expand   : Convert number ranges with hyphens and commas into list of numbers
expand_f : Convert Foundry-style port ranges into list of ports
split    : Split string into list of words
list     : Convert string to list unconditionally
cidr     : Convert netmask to prefix length in IP address string
bool     : Sets the value to False if the line starts with 'no' or else to True

Existing values are not overwritten but will be extended as lists.

Default parameters allow parsing of most configuration files. 
To parse NXOS use indent=2
To parse VSP use indent=0, eob='exit'

"""

# Author: Tim Dorssers

import re
import json
import yaml
import uuid
import ipaddress
import itertools


class Tree(dict):
    """ Autovivificious dictionary """

    def __missing__(self, key):
        """ Implement self[key] when key is not in the dictionary """
        value = self[key] = type(self)()
        return value

    def __str__(self):
        """ Serialize dictionary to JSON formatted string with indents """
        return json.dumps(self, indent=4)

    def merge_retain(self, other):
        """ Update dict with other and concatenate values of existing keys """
        for key in other.keys():
            if key in self:
                v = other[key] if isinstance(other[key], list) else [other[key]]
                if isinstance(self[key], list):
                    self[key] += v
                else:
                    self[key] = [self[key]] + v
            else:
                self[key] = other[key]


class Dissector(object):
    """ Takes a YAML formatted dissector to parse block style documents """

    def __init__(self, stream):
        """ Initialize self """
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
            if 'child' in item:
                self._compile_dissector(item['child'])

    @classmethod
    def from_file(cls, filename):
        """ Alternate constructor that loads a dissector from file """
        with open(filename) as f:
            buf = f.read()
        return cls(buf)

    def parse(self, lines, **kwargs):
        """ Returns a Tree object that contains the parsed iterable """
        return _parse(lines, self.context, **kwargs)

    def parse_file(self, filepath, **kwargs):
        """ Returns a Tree object that contains the parsed file contents """
        with open(filepath) as f:
            return _parse(f, self.context, **kwargs)


def fixup(fd, width=132):
    """ Generator that filters empty lines and concatenates wrapped lines """
    previous = ''
    for line in fd:
        line = line.rstrip()
        if line:
            if len(line) == width:
                previous += line
            else:
                yield previous + line
                previous = ''

def _parse(lines, context, indent=1, eob=None):
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
        # Make list from single item
        if not isinstance(c_stack[-1], list):
            c_stack[-1] = [c_stack[-1]]
        # Iterate over list of dissectors
        for item in c_stack[-1]:
            if 'match' in item:
                m = item['prog'].match(line[indent * level:].rstrip())
            else:
                m = item['prog'].search(line[indent * level:].rstrip())
            # Skip if regular expression does not match
            if not m:
                continue
            # Apply specified action to found named capturing group values
            named_groups = {k: _action(item.get('actionall'), v)
                            for k, v in m.groupdict().items() if v is not None}
            # Use whole match as key if no groups match
            key = m.group(0) if not m.lastindex else None
            if m.re.groups > len(m.re.groupindex):
                # An unnamed group exists, use first unnamed group as key
                key = m.group(next(x for x in itertools.count(1)
                                   if x not in m.re.groupindex.values()))
            if 'parent' in item:
                # Insert specified parent dict and retain reference
                p_result = r_stack[-1][item['parent']]
            else:
                p_result = r_stack[-1]
            if 'key' in item:
                # Use group with specified index as key
                if item['key'] == 'uuid':
                    key = str(uuid.uuid4())  # Use random unique ID as key
                elif item['key'] in range(m.re.groups + 1):
                    key = m.group(item['key'])
            if 'child' in item:
                # Override key by name if specified and apply group action
                key = _action(item.get('action'), item.get('name', key))
                key = [key] if not isinstance(key, list) else key
                # Push branch references to stack
                r_stack.append(p_result[key[0]])
                c_stack.append(item['child'])
                level += 1
                for k in key:
                    # Add to dict using named groups as value
                    p_result[k].merge_retain(named_groups)
            elif 'name' in item:
                # Use 'key' as value or specified value and apply group action
                value = _action(item.get('action'), item.get('value', key))
                # Add the unnamed group and named groups
                named_groups.update({item['name']: value})
                p_result.merge_retain(named_groups)
            elif key:
                # Apply action to key if specified otherwise make list
                key = _action(item.get('action'), key)
                key = [key] if not isinstance(key, list) else key
                for k in key:
                    # Add to dict using named groups as value
                    p_result[k].merge_retain(named_groups)
            else:
                p_result.merge_retain(named_groups)
    return result

def _action(method, value):
    """ Run given method on value """
    if method == 'expand':
        return _expand(value)
    elif method == 'split':
        return value.split()
    elif method == 'list':
        return [value]
    elif method == 'cidr':
        return _cidr(value)
    elif method == 'expand_f':
        return _expand_f(value)
    elif method == 'decrypt_type7':
        return _decrypt_type7(value)
    elif method == 'bool':
        return not value.startswith('no ')
    else:
        return value

def _expand(string):
    """ Convert number ranges with hyphens and commas into list of numbers """
    result = []
    for element in re.split(', *', string):
        # Expand 1-2 to [1, 2] or 1/3-4 to [1/3, 1/4] or 1/5-1/6 to [1/5, 1/6]
        m = re.match(r'([0-9/]*?)(\d+)-\1?(\d+)', element)
        if m:
            for num in range(int(m.group(2)), int(m.group(3)) + 1):
                result.append(m.group(1) + str(num))
        else:
            result.append(element)
    return result

def _expand_f(string):
    """ Convert Foundry-style port ranges into list of ports """
    result = []
    for port_range in re.findall('ethe(?:rnet)? (\S+(?: to )?\S+)', string):
        m = re.match('(\S+\/)(\d+) to \S+\/(\d+)', port_range)
        if m:
            for port in range(int(m.group(2)), int(m.group(3)) + 1):
                result.append(m.group(1) + str(port))
        else:
            result.append(port_range)  # single port
    return result

def _cidr(string):
    """ Convert netmask to prefix length in IP address string """
    try:
        return ipaddress.ip_interface(string.replace(' ', '/')).with_prefixlen
    except ValueError:
        return string

def _decrypt_type7(string):
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

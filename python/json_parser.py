#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# curl -O https://raw.githubusercontent.com/hajimeo/samples/master/python/json_parser.py
# NOTE: https://pypi.python.org/pypi/json-delta/ may do better job
#

import sys, pprint, re, json, getopt

_OPTIONS = {'h': 'help',
            'd': 'debug',
            'l:': 'left=',
            'r:': 'right=',
            'e:': 'exclude=',
            'j:': 'join=',
            't:': 'output_type=',
            'k:': 'key_element=',
            'v:': 'value_element=',
            's': 'sort'}


def usage():
    global _OPTIONS
    print '''A simple JSON Parser/Sorter
If one json file is given, this outputs json strings which is under "key_element" (default "type").
If "value_element" (default "properties") is provided, output json objects which is under "key_element" and "value_element".
If two json files are given, this compares and outputs the difference with JSON format.

    python ./json_parser.py --left=some.json [--right=another.json] [--exclude=exclude regex for key] [--output_type=f|l|r]

To get the latest code:
    curl -O https://raw.githubusercontent.com/hajimeo/samples/master/python/json_parser.py

Ambari API example:
    curl -o config_${_SERVICE}_${_VER}.json -u admin:admin "http://`hostname -f`:8080/api/v1/clusters/$_CLUSTER/configurations/service_config_versions?service_name=$_SERVICE&service_config_version=$_VER"  
    curl -o current_config.json -u admin:admin "http://`hostname -f`:8080/api/v1/clusters/$_CLUSTER/configurations/service_config_versions?is_current=true"

Compare blueprint example:
    
    python ./json_parser.py -l blueprint_1.json -r blueprint_2.json -k 'configurations' -v '' -e '.*(principal|keytab|address|url|uri|host).*'

Option switch (arguments):
    %s
''' % str(_OPTIONS)


class JsonParser:
    DEBUG = False

    def __init__(self):
        self.left = None
        self.right = None
        self.join = 'f'
        self.exclude = None
        self.output_type = None
        # Default is for Ambari API json
        # self.parent_element='configurations'
        self.key_element = 'type'
        self.value_element = 'properties'
        self.sort = False

    @staticmethod
    def fatal(reason):
        sys.stderr.write("FATAL: " + reason + '\n')
        sys.stderr.flush()
        sys.exit(1)

    @staticmethod
    def err(reason, level="ERROR"):
        sys.stderr.write(level + ": " + str(reason) + '\n')
        sys.stderr.flush()
        raise Exception(str(reason))

    @staticmethod
    def warn(reason, level="WARN"):
        sys.stderr.write(level + ": " + str(reason) + '\n')
        sys.stderr.flush()

    @staticmethod
    def debug(reason, level="DEBUG"):
        if JsonParser.DEBUG is True:
            sys.stderr.write(level + ": " + str(reason) + "\n")
            sys.stderr.flush()

    @staticmethod
    def json2dict(filename, key_element=None, value_element=None, sort=True):
        with open(filename) as f:
            rtn = json.load(f)

        if not rtn: return {}

        if sort: rtn = json.loads(json.dumps(rtn, sort_keys=sort))

        # If key_element is specified but couldn't find, it's OK to return an empty dict
        if key_element: return JsonParser.find_key_from_dict(rtn, key_element, value_element)

        return rtn

    @staticmethod
    def compare_dict(l_dict, r_dict, join_type='f', exclude_regex=None, output_type='f'):
        rtn = {}
        regex = None

        if type(l_dict) is not type(r_dict):
            JsonParser.err("Left object is not same as Right object.")

        if isinstance(l_dict, list):
            if len(l_dict) == 1:
                l_dict = l_dict[0]
                r_dict = r_dict[0]
            else:
                for ld in l_dict:
                    if not isinstance(ld, dict):
                        JsonParser.err("TODO: Currently comparing list object is not supported. %s" % (len(l_dict)))
                    ld_keys = ld.keys()
                    if len(ld_keys) != 1:
                        JsonParser.err(
                            "TODO: list=>dict object having multiple keys is not supported. %s" % (len(ld_keys)))
                    rd={}
                    rd[ld_keys[0]] = JsonParser.find_key_from_dict(r_dict, ld_keys[0], None)
                    tmp_rtn = JsonParser.compare_dict(ld[ld_keys[0]], rd[ld_keys[0]], join_type, exclude_regex, output_type)
                    if len(tmp_rtn) > 0: rtn[ld_keys[0]] = tmp_rtn
                return rtn

        if exclude_regex is not None:
            regex = re.compile(exclude_regex)

        # create a list contains unique keys
        for k in list(set(l_dict.keys() + r_dict.keys())):
            if regex is not None:
                if regex.match(k):
                    JsonParser.debug("k matched with %s!" % (exclude_regex))
                    continue

            if k in l_dict and k in r_dict and isinstance(l_dict[k], dict) and isinstance(r_dict[k], dict):
                tmp_rtn = JsonParser.compare_dict(l_dict[k], r_dict[k], join_type, exclude_regex, output_type)
                if len(tmp_rtn) > 0: rtn[k] = tmp_rtn
                continue

            if k in l_dict and k in r_dict and isinstance(l_dict[k], list) and isinstance(r_dict[k], list):
                tmp_rtn = JsonParser.compare_dict(l_dict[k], r_dict[k], join_type, exclude_regex, output_type)
                if len(tmp_rtn) > 0: rtn[k] = tmp_rtn
                continue

            if not k in l_dict or not k in r_dict or l_dict[k] != r_dict[k]:
                if join_type.lower() in ['l', 'i'] and not k in l_dict:
                    continue
                if join_type.lower() in ['r', 'i'] and not k in r_dict:
                    continue

                if not k in l_dict:
                    rtn[k] = JsonParser.output_filter(None, r_dict[k], output_type)
                elif not k in r_dict:
                    rtn[k] = JsonParser.output_filter(l_dict[k], None, output_type)
                else:
                    # Special logic for Ambari "SECRET:xxxx-site:N:prop"
                    if l_dict[k].startswith("SECRET:") and r_dict[k].startswith("SECRET:"):
                        continue
                    rtn[k] = JsonParser.output_filter(l_dict[k], r_dict[k], output_type)
        return rtn

    @staticmethod
    def output_filter(val_l, val_r, output_type='f'):
        if output_type is None or output_type == 'f':
            return [val_l, val_r]
        elif output_type == 'l':
            return val_l
        elif output_type == 'r':
            return val_r

    @staticmethod
    def output_as_str(obj):
        # TODO: need better output format
        print json.dumps(obj, indent=4, sort_keys=True)

    @staticmethod
    def find_key_from_dict(obj, search_key, search_value_key=None):
        # {'search key value':'remaining or search_value_key's value'}
        rtn = {}
        if isinstance(obj, dict):
            # if search_key is found, return a dict
            if search_key in obj:
                try:
                    if not search_value_key:
                        return obj[search_key]

                    if search_value_key in obj:
                        rtn[obj[search_key]] = obj[search_value_key]
                    else:
                        # search_value_key is specified but couldn't find in same hierarchie
                        rtn[obj[search_key]] = None
                except TypeError:
                    JsonParser.err("TypeError for serch_key=%s search_value_key=%s obj[search_key] length=%s" % (search_key, search_value_key, len(obj[search_key])))
                return rtn
            # if couldn't find the search key and its value is a dict object, check recursively (child_key is not used)
            for child_key, child_obj in obj.items():
                tmp_rtn = JsonParser.find_key_from_dict(child_obj, search_key, search_value_key)
                if tmp_rtn:
                    rtn.update(tmp_rtn)
            return rtn
        # NOTE: if object is list, assuming the value of search_key is unique
        if isinstance(obj, list):
            for child_obj in obj:
                tmp_rtn = JsonParser.find_key_from_dict(child_obj, search_key, search_value_key)
                if tmp_rtn:
                    rtn.update(tmp_rtn)
        return rtn

    def setOptions(self, argv, options={'d': 'debug', 'h': 'help'}):
        '''
        Handle command arguments and set *this* class properties
        options example: {'u:':'username=', 'p:':'password=', v':'verbose', 'h':'help'}
        '''
        try:
            opts, args = getopt.getopt(argv, ''.join(options.keys()), options.values())
        except getopt.error, msg:
            print msg
            raise

        try:
            for opt, val in opts:
                opt = opt.replace('-', '')

                if opt in ('h', 'help'):
                    self.usage()
                elif opt in ('d','debug'):
                    JsonParser.DEBUG=True
                elif opt in options.keys():
                    setattr(self, options[opt], True)
                elif opt in options.values():
                    setattr(self, opt, True)
                elif opt + ":" in options.keys():
                    attr = options[opt + ":"].replace('=', '')
                    setattr(self, attr, val)
                elif opt + "=" in options.values():
                    setattr(self, opt, val)
        except TypeError:
            print opts
            raise


if __name__ == '__main__':
    if len(sys.argv) < 2:
        usage()
        sys.exit(0)

    js = JsonParser()
    js.setOptions(sys.argv[1:], _OPTIONS)
    JsonParser.debug((js.left, js.right, js.key_element, js.value_element, js.sort, js.exclude, js.output_type))

    f1_dict = JsonParser.json2dict(js.left, key_element=js.key_element, value_element=js.value_element, sort=js.sort)

    # If only one file, just output value_elements after the key_element
    if not js.right:
        # print json.dumps(f1, indent=0, sort_keys=True, separators=('', '='))
        JsonParser.output_as_str(f1_dict)
        sys.exit(0)

    f2_dict = JsonParser.json2dict(filename=js.right, key_element=js.key_element, value_element=js.value_element, sort=js.sort)
    diff_dict = JsonParser.compare_dict(l_dict=f1_dict, r_dict=f2_dict, join_type=js.join, exclude_regex=js.exclude, output_type=js.output_type)
    # For now, just outputting as JSON (from a dict)
    print json.dumps(diff_dict, indent=4, sort_keys=True)

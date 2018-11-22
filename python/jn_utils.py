#!/usr/bin/env python
# -*- coding: utf-8 -*-
# Python Jupyter Notebook helper/utility functions
# @author: hajime
#

import sys, os, fnmatch, gzip, re
import multiprocessing as mp
import pandas as pd
from sqlalchemy import create_engine
import sqlite3

_LAST_CONN = None


def _mexec(func_and_args, num=2):
    """
    TODO: Execute multiple functions asynchronously (doesn't work with python3?)
    :param func_and_args: list of [func_obj, [args]]
    :param num: number of pool. if None, half of CPUs
    :return: List of multiprocessing.pool.ApplyResult
    >>> def square(x): return x * x
    ...
    >>> def cube(y): return y * y * y
    ...
    >>> rs = _mexec([[square, {'x':1}], [cube, 2]])
    >>> rs[0].get()
    1
    >>> rs[1].get()
    8
    """
    if bool(num) is False: num = int(mp.cpu_count() / 3)
    p = mp.Pool(num)
    rs = []
    for l in func_and_args:
        if len(l) > 1:
            if isinstance(l[1], dict):
                rs += [p.apply_async(l[0], kwds=l[1])]
            elif isinstance(l[1], list):
                rs += [p.apply_async(l[0], args=l[1])]
            else:
                rs += [p.apply_async(l[0], args=[l[1]])]
        else:
            rs += [p.apply_async(l[0])]
    p.close()
    return rs


def dict2global(d, scope, overwrite=False):
    """
    Iterate the given dict and create global variables (key = value)
    NOTE: somehow this function can't be called in another function in Jupyter
    :param d: a dict object
    :param scope: should pass 'globals()' or 'locals()'
    :param overwrite: If True, instead of throwing error, just overwrites with the new value
    :return: void
    >>> dict2global({'a':'test', 'b':'test2'}, globals(), True)
    >>> b == 'test2'
    True
    """
    for k, v in d.items():
        if k in scope and overwrite is False:
            raise ValueError('%s is already used' % (k))
            # continue
        scope[k] = v


### Text/List processing functions
def _chunks(l, n):
    """
    Split/Slice a list by the size 'n'
    From https://stackoverflow.com/questions/312443/how-do-you-split-a-list-into-evenly-sized-chunks
    :param l: A list object
    :param n: Chunk size
    :return: New list
    >>> _chunks([1,2,3,4,5], 2)
    [[1, 2], [3, 4], [5]]
    """
    return [l[i:i + n] for i in range(0, len(l), n)]    #xrange is replaced


def globr(ptn='*', src='./'):
    """
    As Python 2.7's glob does not have recursive option
    :param ptn: glob regex pattern
    :param src: source/importing directory path
    :return: list contains matched file paths
    >>> l = globr();len(l) > 0
    True
    """
    matches = []
    for root, dirnames, filenames in os.walk(src):
        # os walk doesn't sort and almost random
        for filename in fnmatch.filter(sorted(filenames), ptn):
            matches.append(os.path.join(root, filename))
    return matches


### File handling functions
def _read(file):
    """
    Read a single normal or gz file
    :param file:
    :return: file handler
    >>> f = _read(__file__);f.name == __file__
    True
    """
    if not os.path.isfile(file):
        return None
    if file.endswith(".gz"):
        return gzip.open(file, "rt")
    else:
        return open(file, "r")


def load_jsons(src="./", db_conn=1000, include_ptn='*.json', exclude_ptn='physicalPlans|partitions', chunksize=None,
               string_cols=['connectionId', 'planJson', 'json']):
    """
    Find json files from current path and load as pandas dataframes object
    :param src: source/importing directory path
    :param db_conn: If connection object is given, convert JSON to table
    :param include_ptn: Regex string to include some file
    :param exclude_ptn: Regex string to exclude some file
    :param chunksize: Rows will be written in batches of this size at a time. By default, all rows will be written at once
    :param string_cols: As of today, to_sql fails if column is json, so forcing those columns to string
    :return: A tuple contain key=>file relationship and Pandas dataframes objects
    # TODO: add test
    >>> pass
    """
    names_dict = {}
    dfs = {}
    func_and_args = []
    ex = re.compile(exclude_ptn)

    files = globr(include_ptn, src)
    for f in files:
        if ex.search(os.path.basename(f)): continue

        f_name, f_ext = os.path.splitext(os.path.basename(f))
        # sys.stderr.write("Processing %s ...\n" % (str(f_name)))
        new_name = pick_new_key(f_name, names_dict, (bool(db_conn) is False))
        names_dict[new_name] = f
        df_tmp = pd.read_json(f)
        if bool(db_conn):
            try:
                # TODO: Temp workaround "<table>: Error binding parameter <N> - probably unsupported type."
                df_tmp_mod = _avoid_unsupported(df=df_tmp, string_cols=string_cols, name=f_name)
                df_tmp_mod.to_sql(name=f_name, con=db_conn, chunksize=chunksize)
            # Get error message from Exception
            except Exception as e:
                sys.stderr.write("%s: %s\n" % (str(f_name), str(e)))
                raise
        else:
            dfs[new_name] = df_tmp
        # sys.stderr.write("Completed %s .\n" % (str(f_name)))
    return (names_dict, dfs)


def _to_sql(df, tablename, conn=None, chunksize=1000):
    global _LAST_CONN
    if bool(conn) is False: conn = _LAST_CONN
    df.to_sql(name=tablename, con=conn, chunksize=chunksize)
    return tablename


def pick_new_key(name, names_dict, using_1st_char=False, check_global=False):
    """
    Find a non-conflicting a dict key for given name (normally a file name/path)
    :param name: name to be saved or used as a dict key
    :param names_dict: list of names which already exist
    :param using_1st_char: if new name
    :param check_global: if new name is used as a global variable
    :return: a string of a new dict key which hasn't been used
    >>> pick_new_key('test', {'test':'aaa'}, False)
    'test1'
    >>> pick_new_key('test', {'test':'aaa', 't':'bbb'}, True)
    't1'
    """
    if using_1st_char:
        name = name[0]
    new_key = name

    for i in range(0, 9):
        if i > 0:
            new_key = name + str(i)
        if new_key in names_dict and names_dict[new_key] == name:
            break
        if new_key not in names_dict and check_global is False:
            break
        if new_key not in names_dict and check_global is True and new_key not in globals():
            break
    return new_key


def _avoid_unsupported(df, string_cols, name=None):
    """
    Drop DF cols to workaround "<table>: Error binding parameter <N> - probably unsupported type."
    :param df: A *reference* of panda DataFrame
    :param string_cols: List contains column names. Ex. ['connectionId', 'planJson', 'json']
    :return: Modified df
    >>> pass
    """
    keys = df.columns.tolist()
    drop_cols = []
    for k in keys:
        if k in string_cols or k.lower().find('json') > 0:
            # df[k] = df[k].to_string()
            drop_cols.append(k)
    if len(drop_cols) > 0:
        sys.stderr.write("Dropping column:%s from %s.\n" % (str(drop_cols), name))
        return df.drop(columns=drop_cols)
    return df


### Database/DataFrame processing functions
# NOTE: without sqlalchemy is faster
def _db(dbname=':memory:', dbtype='sqlite', isolation_level=None, force_sqlalchemy=False, echo=False):
    """
    Create a DB object. For performance purpose, currently not using sqlalchemy if dbtype is sqlite
    :param dbname: Database name
    :param dbtype: DB type
    :param isolation_level: Isolation level
    :param echo: True output more if sqlalchemy is used
    :return: DB object
    # As testing in connect()
    >>> pass
    """
    if force_sqlalchemy is False and dbtype == 'sqlite':
        return sqlite3.connect(dbname, isolation_level=isolation_level)
    return create_engine(dbtype + ':///' + dbname, isolation_level=isolation_level, echo=echo)


def connect(dbname=':memory:', dbtype='sqlite', isolation_level=None, force_sqlalchemy=False, echo=False):
    """
    Connect to a database
    :param dbname: Database name
    :param dbtype: DB type
    :param isolation_level: Isolation level
    :param echo: True output more if sqlalchemy is used
    :return: connection object
    >>> import sqlite3;s = connect()
    >>> isinstance(s, sqlite3.Connection)
    True
    """
    global _LAST_CONN
    if bool(_LAST_CONN): return _LAST_CONN

    db = _db(dbname=dbname, dbtype=dbtype, isolation_level=isolation_level, force_sqlalchemy=force_sqlalchemy,
             echo=echo)
    if dbtype == 'sqlite':
        if force_sqlalchemy is False:
            db.text_factory = str
        else:
            db.connect().connection.connection.text_factory = str
        # For 'sqlite, 'db' is the connection object because of _db()
        conn = db
    else:
        conn = db.connect()
    if bool(conn): _LAST_CONN = conn
    return conn


def query(sql, conn=None):
    """
    Call fetchall() with given query, expecting SELECT statement
    :param sql: SELECT statement
    :param conn: DB connection object
    :return: fetchall() result
    >>> import sqlite3;s = connect()
    >>> result = query("select name from sqlite_master where type = 'table'")
    >>> bool(result)
    True
    """
    global _LAST_CONN
    if bool(conn) is False: conn = _LAST_CONN
    # return conn.execute(sql).fetchall()
    return pd.read_sql(sql, conn)


def q(sql, conn=None):
    """
    Alias of query
    :param sql: SELECT statement
    :param conn: DB connection object
    :return: fetchall() result
    >>> pass
    """
    return query(sql, conn)


def massage_tuple_for_save(tpl, long_value="", num_cols=None):
    """
    Massage the given tuple to convert to a DataFrame or a Table columns later
    :param tpl: Tuple which contains value of a row
    :param long_value: multi-lines log messages
    :param num_cols: Number of columns in the table to populate missing column as None/NULL
    :return: modified tuple
    >>> massage_tuple_for_save(('a','b'), "aaaa", 4)
    ('a', 'b', None, 'aaaa')
    """
    if bool(num_cols) and len(tpl) < num_cols:
        # - 1 for message
        for i in range(((num_cols - 1) - len(tpl))):
            tpl += (None,)
    tpl += (long_value,)
    return tpl


def _insert2table(conn, tablename, tpls, chunk_size=1000):
    """
    Insert one tuple or tuples to a table
    :param conn: Connection object created by connect()
    :param tablename: Table name
    :param tpls: a Tuple or a list of Tuples, which each Tuple contains values for a row
    :return: execute() method result
    # TODO: a bit hard to test
    >>> pass
    """
    if isinstance(tpls, list):
        first_obj = tpls[0]
    else:
        first_obj = tpls
        tpls = [tpls]
    chunked_list = _chunks(tpls, chunk_size)
    placeholders = ','.join('?' * len(first_obj))
    for l in chunked_list:
        res = conn.executemany("INSERT INTO " + tablename + " VALUES (" + placeholders + ")", l)
        if bool(res) is False:
            return res
    return res


def _find_matching(line, prev_matches, prev_message, begin_re, line_re, size_re=None, time_re=None, num_cols=None):
    """
    Search a line with given regex (compiled)
    :param line: String of a log line
    :param prev_matches: A tuple which contains previously matched groups
    :param prev_message: String contain log's long text which often multi-lines
    :param begin_re: Compiled regex to find the beginning of the log line
    :param line_re: Compiled regex for group match to get the (column) values
    :param size_re: An optional compiled regex to find size related value
    :param time_re: An optional compiled regex to find time related value
    :param num_cols: Number of columns used in massage_tuple_for_save() to populate empty columns with Null
    :return: (tuple, prev_matches, prev_message)
    >>> import re;line = "2018-09-04 12:23:45 test";begin_re=re.compile("^\d\d\d\d-\d\d-\d\d");line_re=re.compile("(^\d\d\d\d-\d\d-\d\d).+(test)")
    >>> _find_matching(line, None, None, begin_re, line_re)
    (None, ('2018-09-04',), 'test')
    """
    tmp_tuple = None
    # If current line is beginning of a new *log* line (eg: ^2018-08-\d\d...)
    if begin_re.search(line):
        # and if previous matches aren't empty, prev_matches is going to be saved
        if bool(prev_matches):
            tmp_tuple = massage_tuple_for_save(tpl=prev_matches, long_value=prev_message, num_cols=num_cols)
            if bool(tmp_tuple) is False:
                # If some error happened, returning without modifying prev_xxxx
                return (tmp_tuple, prev_matches, prev_message)
            prev_message = None
            prev_matches = None

        _matches = line_re.search(line)
        if _matches:
            _tmp_groups = _matches.groups()
            prev_message = _tmp_groups[-1]
            prev_matches = _tmp_groups[:(len(_tmp_groups) - 1)]

            if bool(size_re):
                _size_matches = size_re.search(prev_message)
                if _size_matches:
                    prev_matches += (_size_matches.group(1),)
            if bool(time_re):
                _time_matches = time_re.search(prev_message)
                if _time_matches:
                    prev_matches += (_time_matches.group(1),)
    else:
        prev_message += "" + line  # Looks like each line already has '\n'
    return (tmp_tuple, prev_matches, prev_message)


def _read_file_and_search(file, line_beginning, line_matching, size_regex=None, time_regex=None, num_cols=None):
    """
    Read a file and search each line with given regex
    :param file: A file path
    :param line_beginning: Regex to find the beginning of the line (normally like ^2018-08-21)
    :param line_matching: Regex to capture column values
    :param size_regex: Regex to capture size
    :param time_regex: Regex to capture time/duration
    :param num_cols: Number of columns
    :return: A list of tuples
    # TODO: add test
    >>> pass
    """
    begin_re = re.compile(line_beginning)
    line_re = re.compile(line_matching)
    size_re = re.compile(size_regex) if bool(size_regex) else None
    time_re = re.compile(time_regex) if bool(time_regex) else None
    prev_matches = None
    prev_message = None
    tuples = []

    f = _read(file)
    # Read lines
    for l in f:
        (tmp_tuple, prev_matches, prev_message) = _find_matching(line=l, prev_matches=prev_matches,
                                                                 prev_message=prev_message, begin_re=begin_re,
                                                                 line_re=line_re, size_re=size_re, time_re=time_re,
                                                                 num_cols=num_cols)
        if bool(tmp_tuple):
            tuples += [tmp_tuple]

    # append last message
    if bool(prev_matches):
        tuples += [massage_tuple_for_save(tpl=prev_matches, long_value=prev_message, num_cols=num_cols)]
    return tuples


def logs2table(file_glob, tablename, conn=None,
               col_defs=['datetime', 'loglevel', 'thread', 'jsonstr', 'size', 'time', 'message'],
               num_cols=None, line_beginning="^\d\d\d\d-\d\d-\d\d",
               line_matching="^(\d\d\d\d-\d\d-\d\d \d\d:\d\d:\d\d,\d\d\d) (.+?) \[(.+?)\] (\{.*?\}) (.+)",
               size_regex="[sS]ize = ([0-9]+)", time_regex="time = ([0-9.,]+ ?m?s)",
               max_file_num=10):
    """
    Insert multiple log files into *one* table
    :param conn:  Connection object
    :param file_glob: simple regex used in glob to select files.
    :param tablename: Table name. Required
    :param col_defs: Column definition list or dict (column_name1 data_type, column_name2 data_type, ...)
    :param num_cols: Number of columns in the table. Optional if col_def_str is given.
    :param line_beginning: To detect the beginning of the log entry (normally ^\d\d\d\d-\d\d-\d\d)
    :param line_matching: A group matching regex to separate one log lines into columns
    :param size_regex: (optional) size-like regex to populate 'size' column
    :param time_regex: (optional) time/duration like regex to populate 'time' column
    :param max_file_num: To avoid memory issue, setting max files to import
    :return: Void if no error, or a tuple contains multiple information for debug
    # TODO: add test
    >>> pass
    """
    global _LAST_CONN
    if bool(conn) is False: conn = _LAST_CONN

    # NOTE: as python dict does not guarantee the order, col_def_str is using string
    if bool(num_cols) is False:
        num_cols = len(col_defs)
    files = globr(file_glob)

    if bool(files) is False:
        return False

    if len(files) > max_file_num:
        raise ValueError('Glob: %s returned too many files (%s)' % (file_glob, str(len(files))))

    col_def_str = ""
    if isinstance(col_defs, dict):
        for k, v in col_defs.iteritems():
            if col_def_str != "":
                col_def_str += ", "
            col_def_str += "%s %s" % (k, v)
    else:
        for v in col_defs:
            if col_def_str != "":
                col_def_str += ", "
            col_def_str += "%s TEXT" % (v)

    # If not None, create a table
    if bool(tablename) and bool(col_def_str):
        res = conn.execute("CREATE TABLE IF NOT EXISTS %s (%s)" % (tablename, col_def_str))
        if bool(res) is False:
            return res

    # TODO: Should use Process or Pool class to process per file
    for f in files:
        sys.stderr.write("Processing %s ...\n" % (str(f)))
        tuples = _read_file_and_search(file=f, line_beginning=line_beginning, line_matching=line_matching,
                                       size_regex=size_regex, time_regex=time_regex, num_cols=num_cols)
        if len(tuples) > 0:
            res = _insert2table(conn=conn, tablename=tablename, tpls=tuples)
            if bool(res) is False:
                return res


def logs2dfs(file_glob, col_names=['datetime', 'loglevel', 'thread', 'jsonstr', 'size', 'time', 'message'],
             num_fields=None, line_beginning="^\d\d\d\d-\d\d-\d\d",
             line_matching="^(\d\d\d\d-\d\d-\d\d \d\d:\d\d:\d\d,\d\d\d) (.+?) \[(.+?)\] (\{.*?\}) (.+)",
             size_regex="[sS]ize =? ?([0-9]+)", time_regex="time = ([0-9.,]+ ?m?s)",
             max_file_num=10):
    """
    Convert multiple files to multiple DataFrame objects
    :param file_glob: simple regex used in glob to select files.
    :param col_names: Column definition list or dict (column_name1 data_type, column_name2 data_type, ...)
    :param num_fields: Number of columns in the table. Optional if col_def_str is given.
    :param line_beginning: To detect the beginning of the log entry (normally ^\d\d\d\d-\d\d-\d\d)
    :param line_matching: A group matching regex to separate one log lines into columns
    :param size_regex: (optional) size-like regex to populate 'size' column
    :param time_regex: (optional) time/duration like regex to populate 'time' column
    :param max_file_num: To avoid memory issue, setting max files to import
    :return: A concatenated DF object
    # TODO: add test
    #>>> engine_log = files2dfs(file_glob="debug.2018-08-28.11.log.gz")
    #>>> engine_log[engine_log.loglevel=='DEBUG'].head(10)
    >>> pass
    """
    # NOTE: as python dict does not guarantee the order, col_def_str is using string
    if bool(num_fields) is False:
        num_fields = len(col_names)
    files = globr(file_glob)

    if bool(files) is False:
        return False

    if len(files) > max_file_num:
        raise ValueError('Glob: %s returned too many files (%s)' % (file_glob, str(len(files))))

    # TODO: Should use Process or Pool class to process per file
    dfs = []
    for f in files:
        sys.stderr.write("Processing %s ...\n" % (str(f)))
        tuples = _read_file_and_search(file=f, line_beginning=line_beginning, line_matching=line_matching,
                                       size_regex=size_regex, time_regex=time_regex, num_cols=num_fields)
        if len(tuples) > 0:
            dfs += [pd.DataFrame.from_records(tuples, columns=col_names)]
    return pd.concat(dfs)


def df2csv(df_obj, file_path, mode="w"):
    '''
    Save DataFrame to a CSV file
    :param df_obj: Pandas Data Frame object
    :param file_path: File Path
    :param mode: mode used with open()
    :return: void
    >>> pass
    '''
    current_max_seq_items = pd.options.display.max_seq_items
    if len(df_obj) > pd.options.display.max_seq_items:
        pd.options.display.max_seq_items = len(df_obj)
    f = open(file_path, mode)
    f.write(df_obj.to_csv())
    f.close()
    pd.options.display.max_seq_items = current_max_seq_items


def csv2df(file_path, db_conn=None, table_name=None):
    '''
    Load a CSV file into a DataFrame
    :param file_path: File Path
    :param db_conn: DB connection object. If not empty, also import into a sqlite table
    :return: Pandas DF object
    # TODO: add test
    >>> pass
    '''
    df = pd.read_csv(file_path)
    if bool(db_conn):
        if bool(table_name) is False:
            table_name, ext = os.path.splitext(os.path.basename(file_path))
        df.to_sql(name=table_name, con=db_conn)
    return df


if __name__ == '__main__':
    import doctest

    doctest.testmod(verbose=True)

    # TEST commands
    '''
    file_glob="debug.2018-08-23*.gz"
    tablename="engine_debug_log"
    conn = ju.connect()   # Using dbname will be super slow
    res = ju.files2table(conn=conn, file_glob=file_glob, tablename=tablename)
    print res
    conn.execute("select name from sqlite_master where type = 'table'").fetchall()
    conn.execute("select sql from sqlite_master where name='%s'" % (tablename)).fetchall()
    conn.execute("SELECT MAX(oid) FROM %s" % (tablename)).fetchall()
    '''

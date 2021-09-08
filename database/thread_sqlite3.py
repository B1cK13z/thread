# NOTICE: As required by the Apache License v2.0, this notice is to state this file has been modified by Arachne Digital
# This file has been renamed from `tram_relation.py`
# To see its full history, please use `git log --follow <filename>` to view previous commits and additional contributors

import logging
import sqlite3

from .thread_db import ThreadDB

ENABLE_FOREIGN_KEYS = 'PRAGMA foreign_keys = ON;'


class ThreadSQLite(ThreadDB):
    def __init__(self, database):
        # '?' is the query parameter: https://docs.python.org/3/library/sqlite3.html#sqlite3-placeholders
        super().__init__(query_param='?')
        self.database = database

    async def build(self, schema):
        """Implements ThreadDB.build()"""
        # Ensure the foreign-keys line is prepended to the schema
        schema = ENABLE_FOREIGN_KEYS + '\n' + schema
        try:  # Execute the schema's SQL statements
            with sqlite3.connect(self.database) as conn:
                cursor = conn.cursor()
                cursor.executescript(schema)
                conn.commit()
        except Exception as exc:
            logging.error('! error building db : {}'.format(exc))

    async def _execute_select(self, sql, parameters=None, single_col=False):
        """Implements ThreadDB._execute_select()"""
        with sqlite3.connect(self.database) as conn:
            conn.execute(ENABLE_FOREIGN_KEYS)
            # If we are returning a single column, we just want to retrieve the first part of the row (row[0])
            # else use sqlite3.Row to enable dictionary-conversions
            conn.row_factory = (lambda cur, row: row[0]) if single_col else sqlite3.Row
            cursor = conn.cursor()
            # Execute the SQL query with parameters or not
            if parameters is None:
                cursor.execute(sql)
            else:
                cursor.execute(sql, parameters)
            rows = cursor.fetchall()
            # Return the data as-is if returning a single column, else return the rows as dictionaries
            return rows if single_col else [dict(ix) for ix in rows]

    async def _execute_insert(self, sql, data):
        """Implements ThreadDB._execute_insert()"""
        with sqlite3.connect(self.database) as conn:
            conn.execute(ENABLE_FOREIGN_KEYS)
            cursor = conn.cursor()
            # Execute the SQL statement with the data to be inserted
            cursor.execute(sql, tuple(data.values()))
            saved_id = cursor.lastrowid
            conn.commit()
            return saved_id

    async def update(self, table, where=None, data=None, return_sql=False):
        # If there is no data to update the table with, exit method
        if data is None:
            return None
        # If no WHERE data is specified, default to an empty dictionary
        if where is None:
            where = {}
        # The list of query parameters
        qparams = []
        # Our SQL statement and optional WHERE clause
        sql, where_suffix = 'UPDATE {} SET'.format(table), ''
        # Appending the SET terms; keep a count
        count = 0
        for k, v in data.items():
            # If this is our 2nd (or greater) SET term, separate with a comma
            sql += ',' if count > 0 else ''
            # Add this current term to the SQL statement leaving a ? for the value
            sql += ' {} = ?'.format(k)
            # Update qparams for this value to be substituted
            qparams.append(v)
            count += 1
        # Appending the WHERE terms; keep a count
        count = 0
        for wk, wv in where.items():
            # If this is our 2nd (or greater) WHERE term, separate with an AND
            where_suffix += ' AND' if count > 0 else ''
            # Add this current term like before
            where_suffix += ' {} = ?'.format(wk)
            # Update qparams for this value to be substituted
            qparams.append(wv)
            count += 1
        # Finalise WHERE clause if we had items added to it
        where_suffix = '' if where_suffix == '' else ' WHERE' + where_suffix
        # Add the WHERE clause to the SQL statement
        sql += where_suffix
        if return_sql:
            return tuple([sql, tuple(qparams)])
        # Run the statement by passing qparams as parameters
        with sqlite3.connect(self.database) as conn:
            conn.execute(ENABLE_FOREIGN_KEYS)
            cursor = conn.cursor()
            cursor.execute(sql, tuple(qparams))
            conn.commit()

    async def delete(self, table, data, return_sql=False):
        sql = 'DELETE FROM %s' % table
        qparams = []
        where = next(iter(data))
        value = data.pop(where)
        sql += ' WHERE %s = ?' % where
        qparams.append(value)
        for k, v in data.items():
            sql += ' AND %s = ?' % k
            qparams.append(v)
        if return_sql:
            return tuple([sql, tuple(qparams)])
        with sqlite3.connect(self.database) as conn:
            conn.execute(ENABLE_FOREIGN_KEYS)
            cursor = conn.cursor()
            cursor.execute(sql, tuple(qparams))
            conn.commit()

    async def run_sql_list(self, sql_list=None):
        # Don't do anything if we don't have a list
        if not sql_list:
            return
        with sqlite3.connect(self.database) as conn:
            conn.execute(ENABLE_FOREIGN_KEYS)
            cursor = conn.cursor()
            # Else, execute each item in the list where the first part must be an SQL statement
            # followed by optional parameters
            for item in sql_list:
                if len(item) == 1:
                    cursor.execute(item[0])
                elif len(item) == 2:
                    # execute() takes parameters as a tuple, ensure that is the case
                    parameters = item[1] if type(item[1]) == tuple else tuple(item[1])
                    cursor.execute(item[0], parameters)
            # Finish by committing the changes from the list
            conn.commit()
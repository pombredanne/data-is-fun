#!/usr/bin/env python
"""Provee clases de escritores para utilizar desde el core.

Los escritores reciben diccionarios clave-valor y los escriben en 
distintos medios: bases de datos, xml, binario, etc.
"""


import os
import sys
import logging

__author__ = "Roberto Abdelkader"
__credits__ = ["Roberto Abdelkader"]
__license__ = "GPL"
__version__ = "1.0"
__maintainer__ = "Roberto Abdelkader"
__email__ = "contacto@robertomartinez.es"

class Writer(object):
    """
        Clase padre de los escritores. 
    """

    def __init__(self, config, name):
        self.name = name
        self.type = self.__class__.__name__.lower()
        self.log = logging.getLogger('main.writer.%s' % self.name)
        self.config = config
        self.log.debug("Reader (%s) starting..." % self.name)

    def start(self):
        pass

    def finish(self):
        pass

class plain(Writer):
    """ Class plain.
        Write to plain text with templates.
    """

    def __init__(self, config, name):

        try:
            self._stringio = __import__('cStringIO')
        except:
            self._stringio = __import__('StringIO')

        super(plain, self).__init__(config, name)
        self.template_filename = self.config.get(self.name, "template")

        self.output_location = self.config.get(self.name, "output")

    def start(self):

        try:
            # Restart template file
            self.template_content.seek(0)
        except:
            # Load template file
            try:
                self.template_file = open(self.template_filename, 'r')
            except:
                raise ValueError('Cannot open template (%s)' % self.template_filename)
            self.template_content = self._stringio.StringIO()
            self.template_content.write(self.template_file.read())
            self.template_file.close()
            self.template_content.seek(0)
        
    def add_data(self, data):
        # Try to open output file location
        try:
            output = open(self.output_location % data, 'w')
        except Exception, e:
            raise ValueError(e)

        for line in self.template_content.readlines():
            output.write(line % data)

        output.close()

        self.template_content.seek(0)

    def finish(self):
        self.template_content.close()
        del self.template_content

class mysql(Writer):
    """ Clase mysqlwriter. 
            Prepara y ejecuta queries contra mysql.

    """


    def __init__(self, config, name):
        #
        # apt-get install python-mysqldb
        #
        #import MySQLdb
        #from table_maker import table_maker
        self._mysqldb = __import__('MySQLdb')
        self._table_maker = __import__('table_maker')

        super(mysql, self).__init__(config, name)

        self.hostname = self.config.get(self.name, "hostname")
        self.database = self.config.get(self.name, "database")
        self.username = self.config.get(self.name, "username")
        self.password = self.config.get(self.name, "password")
        self.table = self.config.get(self.name, "table")

        self.force_text_fields = map(lambda x: x.strip(), self.config.get(self.name, "force_text_fields", "string", "").split(","))
        if not self.force_text_fields:
            self.force_text_fields = []

        self.pretend_queries = self.config.get(self.name, "pretend_queries", "boolean")
        if not self.pretend_queries:
            self.flexible_schema = self.config.get(self.name, "flexible_schema", "boolean")
            self.force_text_fields = map(lambda x: x.strip(), self.config.get(self.name, "force_text_fields", "string", "").split(","))
        else:
            self.flexible_schema = False
            self.force_text_fields = []
            self.log.warning("Writer will pretend queries, no changes will be made to database.")

        self.columns = {}
        self.strict_column_checking=self.config.get(self.name, "strict_column_checking", "boolean")

        self.query_type = self.config.get(self.name, "query_type", "string", "insert")
        self.query_where = self.config.get(self.name, "query_where", "string", "")

        self.skip_columns=map(lambda x: x.strip(), self.config.get(self.name, "skip_columns", "string", "").split(","))
        if type(self.skip_columns) != type([]):
            self.skip_columns = []


    def start(self):
        self.db = self._mysqldb.connect(host=self.hostname, user=self.username, passwd=self.password, db=self.database)
        self.cursor = self.db.cursor()

        # Load table schema and table_maker
        self.load_schemer()

        self.added = 0

        self.do_query("SET autocommit = 0")
        self.log.debug("Database writer started...")


    def load_schemer(self):
        try:
            self._get_column_info()
        except:
            if self.pretend_queries:
                self.log.critical('Pretend queries in non existant tables is useless')
                raise SystemExit
            # Table not found
            if self.flexible_schema:
                self.schema = self._table_maker.table_maker(self.table, start_year=2011, end_year=2015, force_text_fields=self.force_text_fields)
                self.log.info("Creating table %s" % self.table)
                self.do_query(str(self.schema))

        self.schema = self._table_maker.table_maker(self.table, start_year=2011, end_year=2015, force_text_fields=self.force_text_fields, fields = self.get_columns().values())
        
    def __del__(self):
        self.cursor.close()
        self.db.close()

    def do_query(self, sql):
        if self.pretend_queries:
            self.log.debug("Pretending query: %s" % sql)
        else:
            self.log.debug("Executing query: %s" % sql)
            self.cursor.execute(sql)

    def do_rollback(self):
        if self.pretend_queries:
            self.log.info("Pretending rollback")
        else:
            self.log.info("Rollback")
            self.db.rollback()

    def do_commit(self):
        if self.pretend_queries:
            self.log.info("Pretending commit")
        else:
            self.log.info("Commit")
            self.db.commit()

    def get_columns(self):
        columns = self.columns.copy()
        for skip in self.skip_columns:
            try:
                columns.__delitem__(skip)
            except:
                pass
        return columns

    def _get_column_info(self):
        """
            Obtiene la lista de columnas de la base de datos.

        """

        self.db.query("SHOW COLUMNS FROM %s" % \
                      self.db.escape_string(self.table) )
        res = self.db.store_result()
        self.columns = {}
        while 1:
            row = res.fetch_row()
            if not row:
                break
            self.columns[row[0][0]] = row[0]

    def make_query(self, data):
        """
            Forma consultas para los datos dados.

        """

        self.added += 1

        if not data:
            return None

        if self.flexible_schema == True:
            prequery = self.schema.add_data(data)
            if prequery:
                if self.flexible_schema:
                    if prequery:
                        self.log.info("Adjusting %s column(s)..." % len(prequery))
                        for query in prequery:
                            self.do_query(query)
                        # Reload. Modified schema!
                        self.load_schemer()
                        return self.make_query(data, self.query_type, self.query_where)
                else:
                    self.log.error('Invalid column data type.')
                    raise ValueError

        if not self.query_type == "insert" and not self.query_type == "update":
            raise Exception("Unknown query type: %s" % self.query_type)

        columns = []
        setstrings = []

        if self.strict_column_checking and not self.columns.keys() == data.keys():
            self.log.debug("\nREGEXP COLUMNS: %s\nTABLE COLUMNS : %s" % (data.keys(),self.columns.keys()) )
            raise Exception("Columns mismatch! Fix regexp or set strict_column_checking=False.")

        # Recorre los valores de data y formatea dependiendo del tipo de consulta
        for key, value in data.iteritems():
            if key in self.skip_columns:
                continue

            if not key in self.columns.keys():
                self.log.debug("Skipping column in regexp: %s" % key)
                continue

            columns.append("`" + key + "`")

            if self.query_type == "insert":
                setstring = str(self.schema.fields[key].transform(value))
            elif self.query_type == "update":
                setstring = "`" + key + "` = " + str(self.schema.fields[key].transform(value))

            setstrings.append(setstring)

        # Transforma la variable query_where sustituyendo las variables por los valores de data
        if self.query_where:
            query_where = "WHERE " + self.query_where % data

        # Forma las consultas finales
        if self.query_type == "insert":
            query = "INSERT INTO %s (%s) VALUES (%s)" % (self.table, ", ".join(columns), ", ".join(setstrings))
        elif self.query_type == "update":
            query = "UPDATE %s SET %s %s" % (self.table, ", ".join(setstrings), query_where)

        return query


    def add_data(self, data):
        self.log.debug("Reader (%s) receive data: %s" % (self.name, data))
        sql_query = self.make_query(data)
        if sql_query:
            self.do_query(sql_query)
        elif self.on_error == "pass":
            self.log.warning("Invalid query, not inserting! Maybe malformed regexp or malformed line?")
        else:
            raise Exception("Empty query!, maybe malformed regexp?")

    def finish(self):
        self.do_commit()

            
class mysql_create(Writer):
    """
        Clase MySqlInspector. 
            Crea tablas de MySQL.

    """

    def __init__(self, config, name):

        self._mysqldb = __import__('MySQLdb')
        self._table_maker = __import__('table_maker')

        super(mysql_create, self).__init__(config, name)

        self.hostname = self.config.get(self.name, "hostname")
        self.database = self.config.get(self.name, "database")
        self.username = self.config.get(self.name, "username")
        self.password = self.config.get(self.name, "password")
        self.table = self.config.get(self.name, "table")

        self.skip_columns=map(lambda x: x.strip(), self.config.get(self.name, "skip_columns", "string", "").split(","))

        self.force_text_fields = map(lambda x: x.strip(), self.config.get(self.name, "force_text_fields", "string", "").split(","))
        if not self.force_text_fields:
            self.force_text_fields = []

        self.must_create = False
        self.columns = {}
        self.pretend_queries = False
        self.added = 0


    def start(self):
        self.db = self._mysqldb.connect(host=self.hostname, user=self.username, passwd=self.password, db=self.database)
        self.cursor = self.db.cursor()
        self.load_schemer()
        self.do_query("SET autocommit = 0")
        self.log.debug("Database inspector started...")

    def load_schemer(self):
        try:
            self._get_column_info()
        except:
            # Table not found
            self.must_create = True

        self.schema = self._table_maker.table_maker(self.table, start_year=2011, end_year=2015, force_text_fields=self.force_text_fields, fields = self.get_columns().values())
        
    def __del__(self):
        self.cursor.close()
        self.db.close()

    def do_query(self, sql):
        self.log.debug("Executing query: %s" % sql)
        self.cursor.execute(sql)

    def do_commit(self):
        self.log.info("Commit")
        self.db.commit()

    def get_columns(self):
        columns = self.columns.copy()
        for skip in self.skip_columns:
            try:
                columns.__delitem__(skip)
            except:
                pass
        return columns

    def _get_column_info(self):
        """
            Obtiene la lista de columnas de la base de datos.

        """
        self.db.query("SHOW COLUMNS FROM %s" % \
                      self.db.escape_string(self.table) )
        res = self.db.store_result()
        self.columns = {}
        while 1:
            row = res.fetch_row()
            if not row:
                break
            self.columns[row[0][0]] = row[0]

    def add_data(self, data):

        self.added += 1

        if not data:
            return None

        for skip in self.skip_columns:
            try:
                data.__delitem__(skip)
            except:
                pass
        self.schema.add_data(data)
        return None

    def finish(self):
        if self.must_create:
            self.log.info("Creating table %s ..." % self.table)
            self.do_query(str(self.schema)) 
        else:
            for key, value in self.schema.last_changes.iteritems():
                if value.has_key('CREATE'):
                    self.log.info("Adding column `%s`" % key)
                    self.do_query(value['CREATE']) 
                if value.has_key('MODIFY'):
                    self.log.info("Changing column `%s`" % key)
                    self.do_query(value['MODIFY']) 

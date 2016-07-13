# -*- coding: utf-8 -*-
# Copyright (c) 2016  Red Hat, Inc.
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.
#
# Written by Petr Šabata <contyk@redhat.com>
#            Ralph Bean <rbean@redhat.com>

"""Database handler functions."""

from sqlalchemy import (
    Column,
    Integer,
    String,
    ForeignKey,
    create_engine,
)
from sqlalchemy.orm import (
    sessionmaker,
    relationship,
    validates,
)
from sqlalchemy.ext.declarative import declarative_base


# Just like koji.BUILD_STATES, except our own codes for modules.
BUILD_STATES = {
    "init": 0,
    "wait": 1,
    "build": 2,
    "done": 3,
    "failed": 4,
    "ready": 5,
}


class RidaBase(object):
    # TODO -- we can implement functionality here common to all our model
    # classes.
    pass


Base = declarative_base(cls=RidaBase)


class Database(object):
    """Class for handling database connections."""

    def __init__(self, config, debug=False):
        """Initialize the database object."""
        self.engine = create_engine(config.db, echo=debug)
        self._session = None  # Lazilly created..

    def __enter__(self):
        return self.session()

    def __exit__(self, *args, **kwargs):
        self._session.close()
        self._session = None

    @property
    def session(self):
        """Database session object."""
        if not self._session:
            Session = sessionmaker(bind=self.engine)
            self._session = Session()
        return self._session

    @classmethod
    def create_tables(cls, db_url, debug=False):
        """ Creates our tables in the database.

        :arg db_url, URL used to connect to the database. The URL contains
        information with regards to the database engine, the host to connect
        to, the user and password and the database name.
        ie: <engine>://<user>:<password>@<host>/<dbname>
        :kwarg debug, a boolean specifying wether we should have the verbose
        output of sqlalchemy or not.
        :return a Database connection that can be used to query to db.
        """
        engine = create_engine(db_url, echo=debug)
        Base.metadata.create_all(engine)
        return cls(db_url, debug=debug)


class Module(Base):
    __tablename__ = "modules"
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    version = Column(String, nullable=False)
    release = Column(String, nullable=False)
    state = Column(Integer, nullable=False)
    modulemd = Column(String, nullable=False)

    @validates('state')
    def validate_state(self, key, field):
        if field in BUILD_STATES.values():
            return field
        if field in BUILD_STATES:
            return BUILD_STATES[field]
        raise ValueError("%s: %s, not in %r" % (key, field, BUILD_STATES))

    def json(self):
        return {
            'id': self.id,
            'name': self.name,
            'version': self.version,
            'release': self.release,
            'state': self.state,

            # This is too spammy..
            #'modulemd': self.modulemd,

            # TODO, show their entire .json() ?
            'builds': [build.id for build in self.builds],
        }


class Build(Base):
    __tablename__ = "builds"
    id = Column(Integer, primary_key=True)
    package = Column(String, nullable=False)
    # XXX: Consider making this a proper ENUM
    format = Column(String, nullable=False)
    task = Column(Integer)
    # XXX: Consider making this a proper ENUM (or an int)
    state = Column(String)

    module_id = Column(Integer, ForeignKey('modules.id'), nullable=False)
    module = relationship('Module', backref='builds', lazy=False)

    def json(self):
        return {
            'id': self.id,
            'package': self.package,
            'format': self.format,
            'task': self.task,
            'state': self.state,
            'module': self.module.id,
        }

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
# Written by Ralph Bean <rbean@redhat.com>
#            Matt Prahl <mprahl@redhat.com>
""" Utility functions for module_build_service. """
from flask import request, url_for
from datetime import datetime
import re
import functools
import time
import shutil
import tempfile
import os
import modulemd
from module_build_service import log, models
from module_build_service.errors import ValidationError, UnprocessableEntity
from module_build_service import app, conf, db, log
from module_build_service.errors import (
    ValidationError, Unauthorized, UnprocessableEntity, Conflict, NotFound)
from multiprocessing.dummy import Pool as ThreadPool

def retry(timeout=120, interval=30, wait_on=Exception):
    """ A decorator that allows to retry a section of code...
    ...until success or timeout.
    """
    def wrapper(function):
        @functools.wraps(function)
        def inner(*args, **kwargs):
            start = time.time()
            while True:
                if (time.time() - start) >= timeout:
                    raise  # This re-raises the last exception.
                try:
                    return function(*args, **kwargs)
                except wait_on as e:
                    log.warn("Exception %r raised from %r.  Retry in %rs" % (
                        e, function, interval))
                    time.sleep(interval)
        return inner
    return wrapper


def start_next_build_batch(config, module, session, builder, components=None):
    """ Starts a next round of the build cycle for a module. """

    import koji  # Placed here to avoid py2/py3 conflicts...

    if any([c.state == koji.BUILD_STATES['BUILDING']
            for c in module.component_builds ]):
        raise ValueError("Cannot start a batch when another is in flight.")

    # The user can either pass in a list of components to 'seed' the batch, or
    # if none are provided then we just select everything that hasn't
    # successfully built yet.
    unbuilt_components = components or [
        c for c in module.component_builds
        if c.state != koji.BUILD_STATES['COMPLETE']
    ]
    module.batch += 1
    for c in unbuilt_components:
        c.batch = module.batch
        c.task_id, c.state, c.state_reason, c.nvr = builder.build(artifact_name=c.package, source=c.scmurl)

        if not c.task_id:
            module.transition(config, models.BUILD_STATES["failed"],
                              "Failed to submit artifact %s to Koji" % (c.package))
            session.add(module)
            break

    session.commit()


def pagination_metadata(p_query):
    """
    Returns a dictionary containing metadata about the paginated query. This must be run as part of a Flask request.
    :param p_query: flask_sqlalchemy.Pagination object
    :return: a dictionary containing metadata about the paginated query
    """

    pagination_data = {
        'page': p_query.page,
        'per_page': p_query.per_page,
        'total': p_query.total,
        'pages': p_query.pages,
        'first': url_for(request.endpoint, page=1, per_page=p_query.per_page, _external=True),
        'last': url_for(request.endpoint, page=p_query.pages, per_page=p_query.per_page, _external=True)
    }

    if p_query.has_prev:
        pagination_data['prev'] = url_for(request.endpoint, page=p_query.prev_num,
                                          per_page=p_query.per_page, _external=True)
    if p_query.has_next:
        pagination_data['next'] = url_for(request.endpoint, page=p_query.next_num,
                                          per_page=p_query.per_page, _external=True)

    return pagination_data


def filter_module_builds(flask_request):
    """
    Returns a flask_sqlalchemy.Pagination object based on the request parameters
    :param request: Flask request object
    :return: flask_sqlalchemy.Pagination
    """
    search_query = dict()
    state = flask_request.args.get('state', None)

    if state:
        if state.isdigit():
            search_query['state'] = state
        else:
            if state in models.BUILD_STATES:
                search_query['state'] = models.BUILD_STATES[state]
            else:
                raise ValidationError('An invalid state was supplied')

    for key in ['name', 'owner']:
        if flask_request.args.get(key, None):
            search_query[key] = flask_request.args[key]

    query = models.ModuleBuild.query

    if search_query:
        query = query.filter_by(**search_query)

    # This is used when filtering the date request parameters, but it is here to avoid recompiling
    utc_iso_datetime_regex = re.compile(r'^(?P<datetime>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(?:\.\d+)?'
                                        r'(?:Z|[-+]00(?::00)?)?$')

    # Filter the query based on date request parameters
    for item in ('submitted', 'modified', 'completed'):
        for context in ('before', 'after'):
            request_arg = '%s_%s' % (item, context) # i.e. submitted_before
            iso_datetime_arg = request.args.get(request_arg, None)

            if iso_datetime_arg:
                iso_datetime_matches = re.match(utc_iso_datetime_regex, iso_datetime_arg)

                if not iso_datetime_matches or not iso_datetime_matches.group('datetime'):
                    raise ValidationError('An invalid Zulu ISO 8601 timestamp was provided for the "%s" parameter'
                                          % request_arg)
                # Converts the ISO 8601 string to a datetime object for SQLAlchemy to use to filter
                item_datetime = datetime.strptime(iso_datetime_matches.group('datetime'), '%Y-%m-%dT%H:%M:%S')
                # Get the database column to filter against
                column = getattr(models.ModuleBuild, 'time_' + item)

                if context == 'after':
                    query = query.filter(column >= item_datetime)
                elif context == 'before':
                    query = query.filter(column <= item_datetime)

    page = flask_request.args.get('page', 1, type=int)
    per_page = flask_request.args.get('per_page', 10, type=int)
    return query.paginate(page, per_page, False)

def submit_module_build(username, url):
    # Import it here, because SCM uses utils methods
    # and fails to import them because of dep-chain.
    import module_build_service.scm

    yaml = ""
    td = None
    try:
        log.debug('Verifying modulemd')
        td = tempfile.mkdtemp()
        scm = module_build_service.scm.SCM(url, conf.scmurls)
        cod = scm.checkout(td)
        cofn = os.path.join(cod, (scm.name + ".yaml"))

        with open(cofn, "r") as mmdfile:
            yaml = mmdfile.read()
    finally:
        try:
            if td is not None:
                shutil.rmtree(td)
        except Exception as e:
            log.warning(
                "Failed to remove temporary directory {!r}: {}".format(
                    td, str(e)))

    mmd = modulemd.ModuleMetadata()
    try:
        mmd.loads(yaml)
    except:
        log.error('Invalid modulemd')
        raise UnprocessableEntity('Invalid modulemd')

    module = models.ModuleBuild.query.filter_by(name=mmd.name,
                                            version=mmd.version,
                                            release=mmd.release).first()
    if module:
        log.debug('Checking whether module build already exist.')
            # TODO: make this configurable, we might want to allow
            # resubmitting any stuck build on DEV no matter the state
        if module.state not in (models.BUILD_STATES['failed'],):
            log.error('Module (state=%s) already exists. '
                        'Only new or failed builds are allowed.'
                        % module.state)
            raise Conflict('Module (state=%s) already exists. '
                            'Only new or failed builds are allowed.'
                            % module.state)
        log.debug('Resuming existing module build %r' % module)
        module.username = username
        module.transition(conf, models.BUILD_STATES["init"])
        log.info("Resumed existing module build in previous state %s"
                    % module.state)
    else:
        log.debug('Creating new module build')
        module = models.ModuleBuild.create(
            db.session,
            conf,
            name=mmd.name,
            version=mmd.version,
            release=mmd.release,
            modulemd=yaml,
            scmurl=url,
            username=username
        )

    # List of (pkg_name, git_url) tuples to be used to check
    # the availability of git URLs paralelly later.
    full_urls = []

    # If the modulemd yaml specifies components, then submit them for build
    if mmd.components:
        for pkgname, pkg in mmd.components.rpms.packages.items():
            try:
                if pkg.get("repository") and not conf.rpms_allow_repository:
                    raise Unauthorized(
                        "Custom component repositories aren't allowed")
                if pkg.get("cache") and not conf.rpms_allow_cache:
                    raise Unauthorized("Custom component caches aren't allowed")
                if not pkg.get("repository"):
                    pkg["repository"] = conf.rpms_default_repository + pkgname
                if not pkg.get("cache"):
                    pkg["cache"] = conf.rpms_default_cache + pkgname
                if not pkg.get("commit"):
                    try:
                        pkg["commit"] = module_build_service.scm.SCM(
                            pkg["repository"]).get_latest()
                    except Exception as e:
                        raise UnprocessableEntity(
                            "Failed to get the latest commit: %s" % pkgname)
            except Exception:
                module.transition(conf, models.BUILD_STATES["failed"])
                db.session.add(module)
                db.session.commit()
                raise

            full_url = pkg["repository"] + "?#" + pkg["commit"]
            full_urls.append((pkgname, full_url))

        log.debug("Checking scm urls")
        # Checks the availability of SCM urls.
        pool = ThreadPool(10)
        err_msgs = pool.map(lambda data: "Cannot checkout {}".format(data[0])
                            if not module_build_service.scm.SCM(data[1]).is_available()
                            else None, full_urls)
        for err_msg in err_msgs:
            if err_msg:
                raise UnprocessableEntity(err_msg)

        for pkgname, pkg in mmd.components.rpms.packages.items():
            full_url = pkg["repository"] + "?#" + pkg["commit"]

            existing_build = models.ComponentBuild.query.filter_by(
                module_id=module.id, package=pkgname).first()
            if (existing_build
                    and existing_build.state != models.BUILD_STATES['done']):
                existing_build.state = models.BUILD_STATES['init']
                db.session.add(existing_build)
            else:
                # XXX: what about components that were present in previous
                # builds but are gone now (component reduction)?
                build = models.ComponentBuild(
                    module_id=module.id,
                    package=pkgname,
                    format="rpms",
                    scmurl=full_url,
                )
                db.session.add(build)

    module.modulemd = mmd.dumps()
    module.transition(conf, models.BUILD_STATES["wait"])
    db.session.add(module)
    db.session.commit()
    log.info("%s submitted build of %s-%s-%s", username, mmd.name,
                mmd.version, mmd.release)
    return module

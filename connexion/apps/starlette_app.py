import logging
import pathlib

import starlette
import uvicorn
from starlette.applications import Starlette
from starlette.routing import Mount, Route

from .abstract import AbstractApp
from ..apis.starlette_api import StarletteApi
from ..exceptions import ProblemException
from ..problem import problem


logger = logging.getLogger('connexion.app.starlette_app')


class StarletteApp(AbstractApp):

    def __init__(self, import_name, server='starlette', **kwargs):
        super().__init__(import_name, StarletteApi, server=server, **kwargs)

    def create_app(self):
        app = Starlette(self.import_name, **self.server_args)
        # adding custom jsonencoder, see:
        # https://github.com/encode/starlette/issues/715
        return app

    def get_root_path(self):
        # see
        # https://github.com/pallets/flask/blob/1.1.x/src/flask/helpers.py#L774
        return ''

    def set_errors_handlers(self):
        # for now, only use 500 internal server error and the connexion ProblemException
        # this is used by default in starlette
        self.add_error_handler(ProblemException, self.common_error_handler)

    @staticmethod
    def common_error_handler(exception):
        if isinstance(exception, ProblemException):
            response = problem(
                status=exception.status, title=exception.title, detail=exception.detail,
                type=exception.type, instance=exception.instance, headers=exception.headers,
                ext=exception.ext
            )
        else:
            if not isinstance(exception, starlette.exceptions.HTTPException):
                # Let starlette handle it
                logging.warning("Unhandled exception occurred: %s",
                                exception)
                raise exception

        return StarletteApi.get_response(response)

    def add_api(self, specification, **kwargs):
        api = super().add_api(specification, **kwargs)
        # TODO: Equivalent of flask blueprint
        # Submount app instead of route(r)s?
        # https://www.starlette.io/routing/#submounting-routes
        self.app.routes.append(Mount('', app=api.app))
        return api

    def add_error_handler(self, error_code, function):
        self.app.add_exception_handler(error_code, function)

    def run(self, port=None, server=None, debug=None, host=None, **options):  # pragma: no cover
        """
        Runs the application on a local development server.
        """
        # this functions is not covered in unit tests because we would effectively testing the mocks

        # overwrite constructor parameter
        if port is not None:
            self.port = port
        elif self.port is None:
            self.port = 5000

        self.host = host or self.host or '0.0.0.0'

        if server is not None:
            self.server = server

        if debug is not None:
            self.debug = debug

        logger.debug('Starting %s HTTP server..', self.server, extra=vars(self))
        if self.server == 'starlette' or self.server == 'uvicorn':
            # Starlette doesn't offer same run() method as flask,
            # we need to use uvicorn (or another ASGI framework) to run it
            # TODO: Run with reload: need to use run with app as type str instead of Starlette
            if 'reload' in options and options['reload']:
                print('reload=True is not supported on uvicorn')
            uvicorn.run(self.app, host=self.host, port=self.port, debug=debug, **options)
        else:
            raise Exception('Server {} not recognized'.format(self.server))

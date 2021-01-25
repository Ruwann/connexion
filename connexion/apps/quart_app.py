import logging

import hypercorn
import quart
from quart.json import JSONEncoder

from .abstract import AbstractApp
from ..apis.quart_api import QuartApi
from ..exceptions import ProblemException
from ..problem import problem

logger = logging.getLogger('connexion.apps.quart_app')


class QuartApp(AbstractApp):

    def __init__(self, import_name, server='hypercorn', **kwargs):
        super().__init__(import_name, QuartApp, server=server, **kwargs)

    def create_app(self):
        app = quart.Quart(self.import_name, **self.server_args)
        app.json_encoder = QuartJSONEncoder
        return app

    def get_root_path(self):
        return pathlib.Path(self.app.root_path)

    def set_errors_handlers(self):
        # Quart uses hypercorn, which doesn't have exceptions like werkzeug
        for error_code in quart.exceptions.default_exceptions:
            self.add_error_handler(error_code, self.common_error_handler)

        self.add_error_handler(ProblemException, self.common_error_handler)

    @staticmethod
    def common_error_handler(exception):
        """
        :type exception: Exception
        """
        if isinstance(exception, ProblemException):
            response = problem(
                status=exception.status, title=exception.title, detail=exception.detail,
                type=exception.type, instance=exception.instance, headers=exception.headers,
                ext=exception.ext)
        else:
            if not isinstance(exception, quart.exceptions.HTTPException):
                exception = quart.exceptions.HTTPStatusException()

            response = problem(title=exception.name, detail=exception.description,
                               status=exception.status_code)

        return QuartApi.get_response(response)

    def add_api(self, specification, **kwargs):
        api = super().add_api(specification, **kwargs)
        self.app.register_blueprint(api.blueprint)
        return api

    def add_error_handler(self, error_code, function):
        # type: (int, FunctionType) -> None
        self.app.register_error_handler(error_code, function)

    def run(self, port=None, server=None, debug=None, host=None, **options):  # pragma: no cover
        """
        Runs the application on a local development server.
        :param port: port to listen to
        :type port: int
        :param server: which asgi server to use
        :type server: str | None
        :param debug: include debugging information
        :type debug: bool
        :param host: the host interface to bind on.
        :type host: str
        :param options: options to be forwarded to the underlying server
        :type options: Any
        """
        # this function is not covered in unit tests because we would effectively testing the mocks

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
        if self.server == 'hypercorn':
            self.app.run(self.host, port=self.port, debug=self.debug, **options)
        else:
            raise Exception('Server {} not recognized'.format(self.server))


class QuartJSONEncoder(JSONEncoder):

    def default(self, object_):
        if isinstance(object_, datetime.datetime):
            if object_.tzinfo:
                # eg: '2015-09-25T23:14:42.588601+00:00'
                return object_.isoformat('T')
            else:
                # No timezone present - assume UTC.
                # eg: '2015-09-25T23:14:42.588601Z'
                return object_.isoformat('T') + 'Z'

        if isinstance(object_, datetime.date):
            return object_.isoformat()

        if isinstance(object_, Decimal):
            return float(object_)

        return super().default(self, object_)

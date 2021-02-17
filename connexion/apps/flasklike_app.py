import logging
import pathlib

from quart.json import JSONEncoder

from .abstract import AbstractApp
from ..apis.quart_api import QuartApi
from ..exceptions import ProblemException
from ..problem import problem

logger = logging.getLogger('connexion.apps.quart_app')


class FlaskLikeApp(AbstractApp):
    """Abstract subclass for apps that implement a Flask-like interface.
    """

    @property
    @abstractmethod
    def framework(self):
        """The framework"""

    @property
    @abstractmethod
    def default_exceptions(self):
        """The default exceptions"""

    def get_root_path(self):
        return pathlib.Path(self.app.root_path)

    def set_errors_handlers(self):
        for error_code in default_exceptions:
            self.add_error_handler(error_code, self.common_error_handler)

        self.add_error_handler(ProblemException, self.common_error_handler)

    def add_api(self, specification, **kwargs):
        api = super().add_api(specification, **kwargs)
        self.app.register_blueprint(api.blueprint)
        return api

    def add_error_handler(self, error_code, function):
        # type: (int, FunctionType) -> None
        self.app.register_error_handler(error_code, function)

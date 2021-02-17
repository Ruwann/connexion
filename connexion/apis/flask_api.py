import logging
import warnings

import flask
import werkzeug.exceptions
from connexion.apis import flask_utils
from connexion.apis.flasklike_api import FlaskLikeApi
from connexion.handlers import AuthErrorHandler
from connexion.jsonifier import Jsonifier
from connexion.lifecycle import ConnexionRequest, ConnexionResponse
from connexion.utils import is_json_mimetype, yamldumper
from connexion.security import FlaskSecurityHandlerFactory
from werkzeug.local import LocalProxy

logger = logging.getLogger('connexion.apis.flask_api')


class FlaskApi(FlaskLikeApi):
    framework = flask
    exceptions_module = werkzeug.exceptions
    internal_handlers_cls = InternalHandlers

    @staticmethod
    def make_security_handler_factory(pass_context_arg_name):
        """ Create default SecurityHandlerFactory to create all security check handlers """
        return FlaskSecurityHandlerFactory(pass_context_arg_name)

    @classmethod
    def get_response(cls, response, mimetype=None, request=None):
        """Gets ConnexionResponse instance for the operation handler
        result. Status Code and Headers for response.  If only body
        data is returned by the endpoint function, then the status
        code will be set to 200 and no headers will be added.

        If the returned object is a flask.Response then it will just
        pass the information needed to recreate it.

        :type response: flask.Response | (flask.Response,) | (flask.Response, int) | (flask.Response, dict) | (flask.Response, int, dict)
        :rtype: ConnexionResponse
        """
        return cls._get_response(response, mimetype=mimetype, extra_context={"url": flask.request.url})

    @classmethod
    def _is_framework_response(cls, response):
        """ Return True if provided response is a framework type """
        return flask_utils.is_flask_response(response)

    @classmethod
    def get_request(cls, *args, **params):
        # type: (*Any, **Any) -> ConnexionRequest
        """Gets ConnexionRequest instance for the operation handler
        result. Status Code and Headers for response.  If only body
        data is returned by the endpoint function, then the status
        code will be set to 200 and no headers will be added.

        If the returned object is a flask.Response then it will just
        pass the information needed to recreate it.

        :rtype: ConnexionRequest
        """
        context_dict = {}
        setattr(flask._request_ctx_stack.top, 'connexion_context', context_dict)
        flask_request = flask.request
        request = ConnexionRequest(
            flask_request.url,
            flask_request.method,
            headers=flask_request.headers,
            form=flask_request.form,
            query=flask_request.args,
            body=flask_request.get_data(),
            json_getter=lambda: flask_request.get_json(silent=True),
            files=flask_request.files,
            path_params=params,
            context=context_dict
        )
        logger.debug('Getting data and status code',
                     extra={
                         'data': request.body,
                         'data_type': type(request.body),
                         'url': request.url
                     })
        return request


context = LocalProxy(FlaskApi._get_context)


class InternalHandlers(object):
    """
    Flask handlers for internally registered endpoints.
    """

    def __init__(self, base_path, options, specification):
        self.base_path = base_path
        self.options = options
        self.specification = specification

    def console_ui_home(self):
        """
        Home page of the OpenAPI Console UI.

        :return:
        """
        openapi_json_route_name = "{blueprint}.{prefix}_openapi_json"
        escaped = flask_utils.flaskify_endpoint(self.base_path)
        openapi_json_route_name = openapi_json_route_name.format(
            blueprint=escaped,
            prefix=escaped
        )
        template_variables = {
            'openapi_spec_url': flask.url_for(openapi_json_route_name)
        }
        if self.options.openapi_console_ui_config is not None:
            template_variables['configUrl'] = 'swagger-ui-config.json'
        return flask.render_template('index.j2', **template_variables)

    def console_ui_static_files(self, filename):
        """
        Servers the static files for the OpenAPI Console UI.

        :param filename: Requested file contents.
        :return:
        """
        # convert PosixPath to str
        static_dir = str(self.options.openapi_console_ui_from_dir)
        return flask.send_from_directory(static_dir, filename)

    def get_json_spec(self):
        return flask.jsonify(self._spec_for_prefix())

    def get_yaml_spec(self):
        return yamldumper(self._spec_for_prefix()), 200, {"Content-Type": "text/yaml"}

    def _spec_for_prefix(self):
        """
        Modify base_path in the spec based on incoming url
        This fixes problems with reverse proxies changing the path.
        """
        base_path = flask.url_for(flask.request.endpoint).rsplit("/", 1)[0]
        return self.specification.with_base_path(base_path).raw

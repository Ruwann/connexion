import asyncio
import logging
import warnings

import hypercorn
import quart

from connexion.apis import flask_utils
from connexion.apis.flasklike_api import FlaskLikeApi
from connexion.handlers import AuthErrorHandler
from connexion.jsonifier import Jsonifier
from connexion.lifecycle import ConnexionRequest, ConnexionResponse
from connexion.security import QuartSecurityHandlerFactory
from connexion.utils import is_json_mimetype, yamldumper

logger = logging.getLogger('connexion.apis.quart_api')


class QuartApi(FlaskLikeApi):
    framework = quart
    exceptions_module = quart.exceptions
    internal_handlers_cls = InternalHandlers

    @staticmethod
    def make_security_handler_factory(pass_context_arg_name):
        """ Create default SecurityHandlerFactory to create all security check handlers """
        return QuartSecurityHandlerFactory(pass_context_arg_name)

    @classmethod
    async def get_response(cls, response, mimetype=None, request=None):
        """Gets ConnexionResponse instance for the operation handler
        result. Status Code and Headers for response.  If only body
        data is returned by the endpoint function, then the status
        code will be set to 200 and no headers will be added.

        If the returned object is a flask.Response then it will just
        pass the information needed to recreate it.

        :type response: flask.Response | (flask.Response,) | (flask.Response, int) | (flask.Response, dict) | (flask.Response, int, dict)
        :rtype: ConnexionResponse
        """
        while asyncio.iscoroutine(response):
            response = await response

        return cls._get_response(response, mimetype=mimetype, extra_context={"url": quart.request.url})

    @classmethod
    def _is_framework_response(cls, response):
        """ Return True if provided response is a framework type """
        # not sure if something similar to werkzeug.wrappers.Response is needed
        # like in the flask_utils function
        return isinstance(response, quart.Response)

    @classmethod
    async def get_request(cls, *args, **params):
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
        setattr(quart._request_ctx_stack.top, 'connexion_context', context_dict)
        quart_request = quart.request
        body = await quart_request.get_data()
        # TODO: Check whether to use quart_json, or whether to use cls.jsonifier.loads(body)
        quart_json = await quart_request.get_json(silent=True)
        request = ConnexionRequest(
            quart_request.url,
            quart_request.method,
            headers=quart_request.headers,
            form=await quart_request.form,
            query=quart_request.args,
            body=body,
            json_getter=lambda: quart_json,
            # json_getter=lambda: cls.jsonifier.loads(body),
            files=await quart_request.files,
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


context = quart.local.LocalProxy(QuartApi._get_context)


class InternalHandlers:
    """
    Quart handlers for internally registered endpoints.
    """

    def __init__(self, base_path, options, specification):
        self.base_path = base_path
        self.options = options
        self.specification = specification

    async def console_ui_home(self):
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
            'openapi_spec_url': quart.url_for(openapi_json_route_name)
        }
        if self.options.openapi_console_ui_config is not None:
            template_variables['configUrl'] = 'swagger-ui-config.json'
        return await quart.render_template('index.j2', **template_variables)

    async def console_ui_static_files(self, filename):
        """
        Servers the static files for the OpenAPI Console UI.

        :param filename: Requested file contents.
        :return:
        """
        # convert PosixPath to str
        static_dir = str(self.options.openapi_console_ui_from_dir)
        return await quart.send_from_directory(static_dir, filename)

    def get_json_spec(self):
        return quart.jsonify(self._spec_for_prefix())

    def get_yaml_spec(self):
        return yamldumper(self._spec_for_prefix()), 200, {"Content-Type": "text/yaml"}

    def _spec_for_prefix(self):
        """
        Modify base_path in the spec based on incoming url
        This fixes problems with reverse proxies changing the path.
        """
        base_path = quart.url_for(quart.request.endpoint).rsplit("/", 1)[0]
        return self.specification.with_base_path(base_path).raw

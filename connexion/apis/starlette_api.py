import json
import logging

import starlette
from starlette.applications import Starlette
from starlette.responses import JSONResponse, Response
from starlette.routing import Router
from starlette.templating import Jinja2Templates

from connexion.lifecycle import ConnexionRequest, ConnexionResponse
from connexion.security.starlette_security_handler_factory import StarletteSecurityHandlerFactory
from connexion.utils import is_json_mimetype, yamldumper
from .abstract import AbstractAPI


logger = logging.getLogger('connexion.apis.starlette_api')


class StarletteApi(AbstractAPI):

    def __init__(self, *args, **kwargs):
        self.app = Starlette()
        super().__init__(*args, **kwargs)

    @staticmethod
    def make_security_handler_factory(pass_context_arg_name):
        return StarletteSecurityHandlerFactory(pass_context_arg_name)

    def _base_path_for_prefix(self, request):
        """
        returns a modified basePath which includes the incoming request's
        path prefix.
        """
        # TODO: check the exact purpose of this function: perhaps request.url is what we want?
        base_path = self.base_path
        if not request.url.path.startswith(self.base_path):
            prefix = request.url.path.split(self.base_path)[0]
            base_path = prefix + base_path
        return base_path

    def _spec_for_prefix(self, request):
        """
        returns a spec with a modified basePath / servers block
        which corresponds to the incoming request path.
        This is needed when behind a path-altering reverse proxy.
        """
        base_path = self._base_path_for_prefix(request)
        return self.specification.with_base_path(base_path).raw

    def add_openapi_json(self):
        logger.debug('Adding spec json: %s/%s', self.base_path,
                     self.options.openapi_spec_path)
        endpoint_name = "{name}_openapi_json".format(name=self.base_path)
        self.app.add_route(self.options.openapi_spec_path,
                              self._get_json_spec,
                              name=endpoint_name)

    async def _get_json_spec(self, request):
        return JSONResponse(self._spec_for_prefix(request))

    def add_openapi_yaml(self):
        if not self.options.openapi_spec_path.endswith("json"):
            return

        openapi_spec_path_yaml = self.options.openapi_spec_path[:-len("json")] + "yaml"
        logger.debug('Adding spec yaml: %s/%s', self.base_path,
                     openapi_spec_path_yaml)
        endpoint_name = "{name}_openapi_yaml".format(name=self.base_path)
        self.app.add_route(
            openapi_spec_path_yaml,
            self._get_yaml_spec,
            name=endpoint_name,
        )

    async def _get_yaml_spec(self, request):
        return Response(
            yamldumper(self._spec_for_prefix(request)),
            media_type='text/yaml',
            status_code=200
        )

    def add_swagger_ui(self):
        logger.debug('Skipping swagger UI for now')
        return
        console_ui_path = self.options.openapi_console_ui_path.strip('/')
        logger.debug('Adding swagger-ui: %s/%s/',
                     self.base_path,
                     console_ui_path)

        if self.options.openapi_console_ui_config is not None:
            config_endpoint_name = "{name}_swagger_ui_config".format(name=self.base_path)
            config_file_url = '/{console_ui_path}/swagger-ui-config.json'.format(
                console_ui_path=console_ui_path)
            self.app.add_route(config_file_url,
                                  lambda: JSONResponse(self.options.openapi_console_ui_config),
                                  name=config_endpoint_name)

        static_endpoint_name = "{name}_swagger_ui_static".format(name=self.base_path)
        static_files_url = '/{console_ui_path}/<path:filename>'.format(
            console_ui_path=console_ui_path)
        self.app.add_route(static_files_url,
                              self.console_ui_static_files,
                              name=static_endpoint_name)

        index_endpoint_name = "{name}_swagger_ui_index".format(name=self.base_path)
        console_ui_url = '/{console_ui_path}/'.format(
            console_ui_path=console_ui_path)
        self.app.add_route(console_ui_url,
                              self._get_console_ui_home,
                              name=index_endpoint_name)

    async def _get_console_ui_home(self):
        """Home page of the OpenAPI Console UI."""
        openapi_json_route_name = "{name}.{prefix}_openapi_json".format(
            name=self.base_path,
            prefix=self.base_path
        )
        # TODO
        # https://www.starlette.io/routing/#reverse-url-lookups
        # For cases where there is no request instance, you can make reverse lookups
        # against the application, although these will only return the URL path.
        template_variables = {
            'openapi_spec_url': starlette.url_for(openapi_json_route_name)
        }
        if self.options.openapi_console_ui_config is not None:
            template_variables['configUrl'] = 'swagger-ui-config.json'

        templates = Jinja2Templates(directory='templates')
        return templates.TemplateResponse('console ui home', **template_variables)

    def add_auth_on_not_found(self, security, security_definitions):
        # TODO
        raise NotImplementedError

    def _add_operation_internal(self, method, path, operation):
        operation_id = operation.operation_id
        logger.debug('... Adding %s -> %s', method.upper(), operation_id,
                     extra=vars(operation))
        endpoint_name = operation_id
        if operation.randomize_endpoint:
            endpoint_name += "|{random_string}".format(
                random_string=''.join(random.SystemRandom().choice(chars) for _ in range(randomize))
            )
        self.app.add_route(
            path,
            operation.function,
            methods=[method],
            name=endpoint_name
        )

    @classmethod
    async def get_response(cls, response, mimetype=None, request=None):
        """Gets ConnexionResponse instance for the operation handler
        result. Status Code and Headers for response.  If only body
        data is returned by the endpoint function, then the status
        code will be set to 200 and no headers will be added.

        If the returned object is a flask.Response then it will just
        pass the information needed to recreate it.

        :type response: starlette.Response | (starlette.Response,) | (starlette.Response, int) | (starlette.Response, dict) | (starlette.Response, int, dict)
        :rtype: ConnexionResponse
        """
        import asyncio
        while asyncio.iscoroutine(response):
            response = await response
        url = str(request.url) if request else ''
        # TODO: figure out how to get request url, might need middleware for it
        return cls._get_response(response, mimetype=mimetype, extra_context={"url": url})

    @classmethod
    def _is_framework_response(cls, response):
        return isinstance(response, starlette.responses.Response)

    @classmethod
    def _framework_to_connexion_response(cls, response: starlette.responses.Response, mimetype):
        return ConnexionResponse(
            status_code=response.status_code,
            mimetype=response.media_type,
            content_type=response.headers.get(b"content-type"),
            headers=response.headers,
            body=response.body,
        )

    @classmethod
    def _connexion_to_framework_response(cls, response, mimetype, extra_context=None):
        starlette_response = cls._build_response(
            mimetype=response.mimetype or mimetype,
            content_type=response.content_type,
            headers=response.headers,
            status_code=response.status_code,
            data=response.body,
            extra_context=extra_context,
        )

    @classmethod
    def _build_response(cls, mimetype, content_type=None, headers=None, status_code=None, data=None, extra_context=None):
        if cls._is_framework_response(data):
            return Response(data, status_code=status_code, headers=headers, media_type=mimetype)

        data, status_code, serialized_mimetype = cls._prepare_body_and_status_code(data=data, mimetype=mimetype, status_code=status_code, extra_context=extra_context)

        kwargs = {
            'content': data,
            'status_code': status_code,
            'headers': headers,
            'media_type': serialized_mimetype or mimetype,
            # content_type header is set automatically in starlette
        }
        kwargs = {k: v for k, v in kwargs.items() if v is not None}
        return Response(**kwargs)

    @classmethod
    def _serialize_data(cls, data, mimetype):
        # TODO
        raise NotImplementedError
        return body, mimetype

    @classmethod
    async def get_request(cls, request: starlette.requests.Request):
        """Convert Starlette Request to connexion

        Args:
            request (starlette.requests.Request): instance of starlette request

        Returns:
            ConnexionRequest: connexion request instance
        """
        context_dict = {}
        # context_dict.update(request.state)
        # TODO: request context: middleware?
        # https://github.com/encode/starlette/issues/420
        # https://github.com/tomwojcik/starlette-context
        body = await request.body()
        form = await request.form()
        try:
            starlette_json = await request.json()
        except json.JSONDecodeError:
            # Similar to flask.get_json(silent=True), we return None if it fails
            starlette_json = None
        logger.debug('Getting data and status code',
                      extra={'body': body, 'data_type': type(body), 'url': request.url})
        request = ConnexionRequest(
            request.url,
            request.method,
            headers=request.headers,
            form=form,
            query=request.query_params,
            body=body,
            json_getter=lambda: starlette_json,
            files=form,  # aiohttp specifies empty dict here?
            path_params=request.path_params,
            context=context_dict
        )
        return request

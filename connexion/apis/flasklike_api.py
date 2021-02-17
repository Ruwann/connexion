import logging
import warnings
from abc import abstractmethod

from connexion.apis import flask_utils
from connexion.apis.abstract import AbstractAPI
from connexion.handlers import AuthErrorHandler
from connexion.jsonifier import Jsonifier
from connexion.lifecycle import ConnexionRequest, ConnexionResponse
from connexion.utils import is_json_mimetype, yamldumper

logger = logging.getLogger('connexion.apis.flasklike_api')

class FlaskLikeApi(AbstractAPI):
    """Abstract subclass for apis that implement a Flask-like interface.
    """

    @property
    @abstractmethod
    def framework(self):
        """The framework"""

    @property
    @abstractmethod
    def exceptions_module(self):
        """The exceptions_module"""

    @property
    @abstractmethod
    def internal_handlers_cls(self):
        """The internal_handlers_cls"""

    def _set_base_path(self, base_path):
        super()._set_base_path(base_path)
        self._set_blueprint()

    def _set_blueprint(self):
        logger.debug('Creating API blueprint: %s', self.base_path)
        # Check if flaskify_endpoint is needed
        endpoint = flask_utils.flaskify_endpoint(self.base_path)
        self.blueprint = self.framework.Blueprint(
            endpoint, __name__, url_prefix=self.base_path,
            template_folder=str(self.options.openapi_console_ui_from_dir)
        )

    def add_openapi_json(self):
        """
        Adds spec json to {base_path}/swagger.json
        or {base_path}/openapi.json (for oas3)
        """
        logger.debug('Adding spec json: %s/%s', self.base_path,
                     self.options.openapi_spec_path)
        endpoint_name = "{name}_openapi_json".format(name=self.blueprint.name)

        self.blueprint.add_url_rule(self.options.openapi_spec_path,
                                    endpoint_name,
                                    self._handlers.get_json_spec)

    def add_openapi_yaml(self):
        """
        Adds spec yaml to {base_path}/swagger.yaml
        or {base_path}/openapi.yaml (for oas3)
        """
        if not self.options.openapi_spec_path.endswith("json"):
            return

        openapi_spec_path_yaml = \
            self.options.openapi_spec_path[:-len("json")] + "yaml"
        logger.debug('Adding spec yaml: %s/%s', self.base_path,
                     openapi_spec_path_yaml)
        endpoint_name = "{name}_openapi_yaml".format(name=self.blueprint.name)
        self.blueprint.add_url_rule(
            openapi_spec_path_yaml,
            endpoint_name,
            self._handlers.get_yaml_spec
        )

    def add_swagger_ui(self):
        """
        Adds swagger ui to {base_path}/ui/
        """
        console_ui_path = self.options.openapi_console_ui_path.strip('/')
        logger.debug('Adding swagger-ui: %s/%s/',
                     self.base_path,
                     console_ui_path)

        if self.options.openapi_console_ui_config is not None:
            config_endpoint_name = "{name}_swagger_ui_config".format(name=self.blueprint.name)
            config_file_url = '/{console_ui_path}/swagger-ui-config.json'.format(
                console_ui_path=console_ui_path)

            self.blueprint.add_url_rule(config_file_url,
                                        config_endpoint_name,
                                        lambda: quart.jsonify(self.options.openapi_console_ui_config))

        static_endpoint_name = "{name}_swagger_ui_static".format(name=self.blueprint.name)
        static_files_url = '/{console_ui_path}/<path:filename>'.format(
            console_ui_path=console_ui_path)

        self.blueprint.add_url_rule(static_files_url,
                                    static_endpoint_name,
                                    self._handlers.console_ui_static_files)

        index_endpoint_name = "{name}_swagger_ui_index".format(name=self.blueprint.name)
        console_ui_url = '/{console_ui_path}/'.format(
            console_ui_path=console_ui_path)

        self.blueprint.add_url_rule(console_ui_url,
                                    index_endpoint_name,
                                    self._handlers.console_ui_home)

    def add_auth_on_not_found(self, security, security_definitions):
        """
        Adds a 404 error handler to authenticate and only expose the 404 status if the security validation pass.
        """
        logger.debug('Adding path not found authentication')
        not_found_error = AuthErrorHandler(self, quart.exceptions.NotFound(), security=security,
                                           security_definitions=security_definitions)
        endpoint_name = "{name}_not_found".format(name=self.blueprint.name)
        self.blueprint.add_url_rule('/<path:invalid_path>', endpoint_name, not_found_error.function)

    def _add_operation_internal(self, method, path, operation):
        operation_id = operation.operation_id
        logger.debug('... Adding %s -> %s', method.upper(), operation_id,
                     extra=vars(operation))

        framework_path = flask_utils.flaskify_path(path, operation.get_path_parameter_types())
        endpoint_name = flask_utils.flaskify_endpoint(operation.operation_id,
                                                      operation.randomize_endpoint)
        function = operation.function
        self.blueprint.add_url_rule(framework_path, endpoint_name, function, methods=[method])

    @property
    def _handlers(self):
        # type: () -> InternalHandlers
        if not hasattr(self, '_internal_handlers'):
            self._internal_handlers = self.internal_handlers_cls(self.base_path, self.options, self.specification)
        return self._internal_handlers

    @classmethod
    def _framework_to_connexion_response(cls, response, mimetype):
        """ Cast framework response class to ConnexionResponse used for schema validation """
        return ConnexionResponse(
            status_code=response.status_code,
            mimetype=response.mimetype,
            content_type=response.content_type,
            headers=response.headers,
            body=response.get_data(),
        )

    @classmethod
    def _connexion_to_framework_response(cls, response, mimetype, extra_context=None):
        """ Cast ConnexionResponse to framework response class """
        framework_response = cls._build_response(
            mimetype=response.mimetype or mimetype,
            content_type=response.content_type,
            headers=response.headers,
            status_code=response.status_code,
            data=response.body,
            extra_context=extra_context,
            )

        return framework_response


    @classmethod
    def _build_response(cls, mimetype, content_type=None, headers=None, status_code=None, data=None, extra_context=None):
        if cls._is_framework_response(data):
            return cls.framework.current_app.make_response((data, status_code, headers))

        data, status_code, serialized_mimetype = cls._prepare_body_and_status_code(data=data, mimetype=mimetype, status_code=status_code, extra_context=extra_context)

        kwargs = {
            'mimetype': mimetype or serialized_mimetype,
            'content_type': content_type,
            'headers': headers,
            'response': data,
            'status': status_code
        }
        kwargs = {k: v for k, v in kwargs.items() if v is not None}
        return cls.framework.current_app.response_class(**kwargs)

    @classmethod
    def _serialize_data(cls, data, mimetype):
        # TODO: harmonize flask and aiohttp serialization when mimetype=None or mimetype is not JSON
        #       (cases where it might not make sense to jsonify the data)
        if (isinstance(mimetype, str) and is_json_mimetype(mimetype)):
            body = cls.jsonifier.dumps(data)
        elif not (isinstance(data, bytes) or isinstance(data, str)):
            warnings.warn(
                "Implicit (flask) JSON serialization will change in the next major version. "
                "This is triggered because a response body is being serialized as JSON "
                "even though the mimetype is not a JSON type. "
                "This will be replaced by something that is mimetype-specific and may "
                "raise an error instead of silently converting everything to JSON. "
                "Please make sure to specify media/mime types in your specs.",
                FutureWarning  # a Deprecation targeted at application users.
            )
            body = cls.jsonifier.dumps(data)
        else:
            body = data

        return body, mimetype

    @classmethod
    def _set_jsonifier(cls):
        """
        Use Flask specific JSON loader
        """
        cls.jsonifier = Jsonifier(cls.framework.json, indent=2)

    @classmethod
    def _get_context():
        return getattr(cls.framework._request_ctx_stack.top, 'connexion_context')

from module_build_service import conf
from base import GenericBuilder
from KojiModuleBuilder import KojiModuleBuilder

__all__ = [
    GenericBuilder
]


GenericBuilder.register_backend_class(KojiModuleBuilder)

from MockModuleBuilder import MockModuleBuilder
GenericBuilder.register_backend_class(MockModuleBuilder)

if conf.system == "copr":
    from CoprModuleBuilder import CoprModuleBuilder
    GenericBuilder.register_backend_class(CoprModuleBuilder)

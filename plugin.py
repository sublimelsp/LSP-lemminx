from LSP.plugin import DottedDict
from LSP.plugin.core.typing import List, Optional
from lsp_utils import GenericClientHandler
from lsp_utils import ServerResourceInterface
from lsp_utils import ServerStatus
from urllib.request import urlretrieve
import hashlib
import os
import shutil
import sublime


class LemminxServerResource(ServerResourceInterface):

    SERVER_URL = "https://repo.eclipse.org/content/repositories/lemminx-releases/org/eclipse/lemminx/org.eclipse.lemminx/0.14.1/org.eclipse.lemminx-0.14.1-uber.jar"
    SERVER_SHA256 = "fb38a67211b53c86ee96892a600760b3085e942ceb1c6249e8edc52993304a03"

    def __init__(self, storage_path: str) -> None:
        self._storage_path = storage_path
        self._status = ServerStatus.UNINITIALIZED

    # --- ServerResourceInterface handlers

    @property
    def binary_path(self) -> str:
        return self.server_jar

    def needs_installation(self) -> bool:
        if self.is_binary_up_to_date():
            self._status = ServerStatus.READY
            return False
        return True

    def install_or_update(self) -> None:
        # download new server binary
        os.makedirs(self.server_dir, exist_ok=True)
        urlretrieve(url=self.SERVER_URL, filename=self.server_jar)
        if not self.is_binary_up_to_date():
            os.remove(self.server_jar)
            raise RuntimeError("Error downloading XML server binary!")

        # clear old server binaries
        for file_name in os.listdir(self.server_dir):
            if os.path.splitext(file_name)[1].lower() != ".jar":
                continue

            try:
                file_path = os.path.join(self.server_dir, file_name)
                if not os.path.samefile(file_path, self.server_jar):
                    os.remove(file_path)
            except FileNotFoundError:
                pass
        self._status = ServerStatus.READY

    def get_status(self) -> int:
        return self._status

    # --- Internal handlers

    def is_binary_up_to_date(self):
        try:
            with open(self.server_jar, "rb") as stream:
                checksum = hashlib.sha256(stream.read()).hexdigest()
                return checksum.lower() == self.SERVER_SHA256.lower()
        except OSError:
            pass
        return False

    @property
    def server_dir(self):
        return os.path.join(self._storage_path, __package__)

    @property
    def server_jar(self):
        return os.path.join(self.server_dir, self.SERVER_URL.rsplit("/", 1)[1])


class LemminxPlugin(GenericClientHandler):

    package_name = __package__
    _server = None  # type: Optional[LemminxServerResource]

    @classmethod
    def get_displayed_name(cls) -> str:
        return "lemminx"

    @classmethod
    def manages_server(cls) -> bool:
        return True

    @classmethod
    def get_command(cls) -> List[str]:
        return ["java", "-jar", cls.get_server().server_jar]

    @classmethod
    def get_server(cls) -> Optional[LemminxServerResource]:
        if not cls._server:
            cls._server = LemminxServerResource(cls.storage_path())
        return cls._server

    def on_settings_changed(self, settings: DottedDict) -> None:
        super().on_settings_changed(settings)

        server = self.get_server()
        if server:
            settings.set("xml.server.workDir", server.server_dir)


def plugin_loaded() -> None:
    LemminxPlugin.setup()


def plugin_unloaded() -> None:
    LemminxPlugin.cleanup()

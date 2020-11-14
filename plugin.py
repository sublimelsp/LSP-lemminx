import os
import hashlib
import shutil
import sublime

from urllib.request import urlretrieve

from LSP.plugin import AbstractPlugin


SERVER_URL = "https://repo.eclipse.org/content/repositories/lemminx-releases/org/eclipse/lemminx/org.eclipse.lemminx/0.14.1/org.eclipse.lemminx-0.14.1-uber.jar"
SERVER_SHA256 = "fb38a67211b53c86ee96892a600760b3085e942ceb1c6249e8edc52993304a03"


class LemminxPlugin(AbstractPlugin):

    server_dir = ""
    server_jar = ""

    @classmethod
    def name(cls):
        return "lemminx"

    @classmethod
    def configuration(cls):
        name = "LSP-" + cls.name()
        base_name = name + ".sublime-settings"
        file_path = "Packages/{}/{}".format(__package__, base_name)
        settings = sublime.load_settings(base_name)

        # prepare server command
        cls.server_dir = os.path.join(cls.storage_path(), __package__)
        cls.server_jar = os.path.join(cls.server_dir, SERVER_URL.rsplit("/", 1)[1])
        settings.set("command", ["java", "-jar", cls.server_jar])

        # setup scheme cache directory
        client_settings = settings.get("settings")
        client_settings["xml.server.workDir"] = cls.server_dir
        settings.set("settings", client_settings)

        return settings, file_path

    @classmethod
    def needs_update_or_installation(cls):
        try:
            # move from cache path to package storage
            old_server_dir = os.path.join(sublime.cache_path(), __package__)
            if os.path.isdir(old_server_dir):
                shutil.move(old_server_dir, cls.server_dir)
            # check hash
            with open(cls.server_jar, "rb") as stream:
                checksum = hashlib.sha256(stream.read()).hexdigest()
                return checksum.lower() != SERVER_SHA256.lower()
        except OSError:
            pass
        return True

    @classmethod
    def install_or_update(cls):
        # download new server binary
        os.makedirs(cls.server_dir, exist_ok=True)
        urlretrieve(url=SERVER_URL, filename=cls.server_jar)
        if cls.needs_update_or_installation():
            os.remove(cls.server_jar)
            raise RuntimeError("Error downloading XML server binary!")

        # clear old server binaries
        for file_name in os.listdir(cls.server_dir):
            if os.path.splitext(file_name)[1].lower() != ".jar":
                continue

            try:
                file_path = os.path.join(cls.server_dir, file_name)
                if not os.path.samefile(file_path, cls.server_jar):
                    os.remove(file_path)
            except FileNotFoundError:
                pass

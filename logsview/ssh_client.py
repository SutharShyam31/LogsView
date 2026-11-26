from dataclasses import dataclass
from io import StringIO


@dataclass
class CommandResult:
    stdout: str
    stderr: str
    exit_code: int


def _load_private_key(pem_content: str, passphrase: str | None = None):
    import paramiko
    errors = []
    for cls in (paramiko.Ed25519Key, paramiko.ECDSAKey, paramiko.RSAKey, paramiko.DSSKey):
        try:
            return cls.from_private_key(StringIO(pem_content), password=passphrase or None)
        except paramiko.SSHException as exc:
            errors.append(f"{cls.__name__}: {exc}")
    raise ValueError(f"unsupported private key format. tried: {'; '.join(errors)}")


def _connect_kwargs(host: str, port: int, username: str, password: str | None, key: str | None, key_passphrase: str | None, sock=None) -> dict:
    kw = {
        "hostname": host,
        "port": port,
        "username": username,
        "timeout": 15,
        "allow_agent": False,
        "look_for_keys": False,
    }
    if sock is not None:
        kw["sock"] = sock
    if key:
        kw["pkey"] = _load_private_key(key, key_passphrase)
    elif password:
        kw["password"] = password
    else:
        raise ValueError("ssh needs either a password or a private key")
    return kw


class SSHClient:
    def __init__(
        self,
        host: str,
        port: int,
        username: str,
        password: str | None = None,
        key: str | None = None,
        key_passphrase: str | None = None,
        bastion: dict | None = None,
    ):
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.key = key
        self.key_passphrase = key_passphrase
        self.bastion = bastion
        self._client = None
        self._bastion_client = None

    def connect(self) -> None:
        import paramiko
        sock = None
        if self.bastion:
            b = paramiko.SSHClient()
            b.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            b.connect(**_connect_kwargs(
                host=self.bastion["host"],
                port=self.bastion.get("port", 22),
                username=self.bastion["username"],
                password=self.bastion.get("password"),
                key=self.bastion.get("private_key") or self.bastion.get("key"),
                key_passphrase=self.bastion.get("key_passphrase"),
            ))
            self._bastion_client = b
            transport = b.get_transport()
            sock = transport.open_channel(
                "direct-tcpip",
                (self.host, self.port),
                ("127.0.0.1", 0),
            )

        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        client.connect(**_connect_kwargs(
            host=self.host,
            port=self.port,
            username=self.username,
            password=self.password,
            key=self.key,
            key_passphrase=self.key_passphrase,
            sock=sock,
        ))
        self._client = client

    def run(self, command: str, timeout: int = 20) -> CommandResult:
        if self._client is None:
            self.connect()
        stdin, stdout, stderr = self._client.exec_command(command, timeout=timeout)
        out = stdout.read().decode("utf-8", errors="replace")
        err = stderr.read().decode("utf-8", errors="replace")
        code = stdout.channel.recv_exit_status()
        return CommandResult(stdout=out, stderr=err, exit_code=code)

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None
        if self._bastion_client is not None:
            self._bastion_client.close()
            self._bastion_client = None

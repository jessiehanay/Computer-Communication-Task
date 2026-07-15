import mimetypes
import socket
import threading
from pathlib import Path
from urllib.parse import unquote, urlsplit

STATIC_ROOT = Path(__file__).parent / "static"


HOST = "127.0.0.1"
PORT = 8004
RECV_SIZE = 4096
MAX_HEADER_SIZE = 16 * 1024

STATUS_REASONS = {
    200: "OK",
    400: "Bad Request",
    403: "Forbidden",
    404: "Not Found",
    405: "Method Not Allowed",
    431: "Request Header Fields Too Large",
    505: "HTTP Version Not Supported",
}

ALLOWED_DIRECTORIES = {
    "public",
    "images",
}


def read_http_headers(client_socket):
    """
    Read data until the HTTP header terminator is received.

    A single recv() call is not guaranteed to contain
    the complete HTTP request.
    """
    data = bytearray()

    # Read until the HTTPS header termintaor; headers may arrive in multiple chunks
    while b"\r\n\r\n" not in data:
        chunk = client_socket.recv(RECV_SIZE)

        if not chunk:
            raise ValueError("Client closed the connection before sending headers")

        data.extend(chunk)

        if len(data) > MAX_HEADER_SIZE:
            raise OverflowError("HTTP headers are too large")

    header_bytes, _, _ = data.partition(b"\r\n\r\n")

    try:
        header_text = header_bytes.decode("iso-8859-1")
        print(f"HTTP headers:\n{header_text}")

        return header_text
    except UnicodeDecodeError as exc:
        raise ValueError("Invalid HTTP header encoding") from exc


def parse_request(header_text):
    """
    Parse the first HTTP request line.

    Example:
    GET /public/index.html HTTP/1.1
    """
    lines = header_text.split("\r\n")

    if not lines or not lines[0]:
        raise ValueError("Missing request line")

    request_line = lines[0]
    parts = request_line.split()

    if len(parts) != 3:
        raise ValueError("Malformed request line")

    method, target, version = parts

    return method, target, version


def build_response(
    status_code,
    body=b"",
    content_type="text/plain; charset=utf-8",
):
    """
    Build a complete HTTP/1.0 response.
    """
    reason = STATUS_REASONS.get(status_code, "Unknown")

    headers = [
        f"HTTP/1.0 {status_code} {reason}",
        f"Content-Length: {len(body)}",
        f"Content-Type: {content_type}",
        "Connection: close",
        "",
        "",
    ]

    #Build a standard HTTP/1.0 response with the required doucble CRLF seperator
    header_bytes = "\r\n".join(headers).encode("ascii")

    return header_bytes + body


def build_error_response(status_code, message):
    reason = STATUS_REASONS[status_code]

    body = (f"{status_code} {reason}\n" f"{message}\n").encode("utf-8")

    return build_response(
        status_code,
        body,
        "text/plain; charset=utf-8",
    )


def resolve_requested_file(target):
    """
    Convert the requested URL into a safe local file path.
    """
    raw_path = urlsplit(target).path

    try:
        decoded_path = unquote(raw_path, errors="strict")
    except UnicodeDecodeError as exc:
        raise ValueError("Invalid URL encoding") from exc

    # Reject null bytes and Windows-style path separators
    if "\x00" in decoded_path or "\\" in decoded_path:
         raise PermissionError("Invalid path")

    # Default page
    if decoded_path == "/":
        decoded_path = "/public/index.html"

    path_parts = [part for part in decoded_path.split("/") if part not in ("", ".")]

    if ".." in path_parts:
        raise PermissionError("Directory traversal attempt")

    if not path_parts:
        raise PermissionError("Invalid path")

    first_directory = path_parts[0]

    if first_directory not in ALLOWED_DIRECTORIES:
        raise PermissionError("Directory is not allowed")

    requested_path = (STATIC_ROOT / Path(*path_parts)).resolve()
    static_root = STATIC_ROOT.resolve()

    # Additional protection against escaping the static directory.
    if requested_path != static_root and static_root not in requested_path.parents:
        raise PermissionError("Path escapes static root")

    return requested_path


def handle_client(client_socket, client_address):
    """
    Handle one client connection.
    """
    client_ip, client_port = client_address

    print(f"Connection from {client_ip}:{client_port}")

    try:
        header_text = read_http_headers(client_socket)

        method, target, version = parse_request(header_text)

        print(f"Request: {method} {target} {version}")

        if method != "GET":
            response = build_error_response(
                405,
                "Only the GET method is supported",
            )
            client_socket.sendall(response)
            return

        if version not in ("HTTP/1.0", "HTTP/1.1"):
            response = build_error_response(
                505,
                "Supported versions: HTTP/1.0 and HTTP/1.1",
            )
            client_socket.sendall(response)
            return

        requested_file = resolve_requested_file(target)

        if not requested_file.is_file():
            response = build_error_response(
                404,
                "The requested file was not found",
            )
            client_socket.sendall(response)
            return

        body = requested_file.read_bytes()

        content_type, _ = mimetypes.guess_type(requested_file.name)

        if content_type is None:
            content_type = "application/octet-stream"

        response = build_response(
            200,
            body,
            content_type,
        )

        client_socket.sendall(response)

    except OverflowError:
        response = build_error_response(
            431,
            "The HTTP headers are too large",
        )
        client_socket.sendall(response)

    except PermissionError:
        response = build_error_response(
            403,
            "Access to the requested path is forbidden",
        )
        client_socket.sendall(response)

    except (ValueError, UnicodeError):
        response = build_error_response(
            400,
            "The HTTP request is malformed",
        )
        client_socket.sendall(response)

    except OSError as exc:
        print(f"Socket or file error: {exc}")

    finally:
        #Ensure the socket is always closed to prevent leaks
        client_socket.close()

def run_server():
    # STATIC_ROOT.mkdir(exist_ok=True)

    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    
    server_socket.setsockopt(
        socket.SOL_SOCKET,
        socket.SO_REUSEADDR,
        1,
    )

    print(f"binding to {HOST}:{PORT} ...")
    server_socket.bind((HOST, PORT))

    print("Start listening...")
    server_socket.listen()

    try:
        while True:
            print("Waiting for connection (accept)...")
            client_socket, client_address = server_socket.accept()

            #We spawn a new thread for every client to prevent head-of-line blocking
            thread = threading.Thread(
                target=handle_client,
                args=(client_socket, client_address)
            )
            thread.daemon = True #Threads will terminate when the main program exits
            thread.start()
            
            print(f"Accepted connection from {client_address}, {client_socket}")

    finally:
        print("Closing server socket...")
        server_socket.close()
        print("done")


if __name__ == "__main__":
    print("Starting server...")
    run_server()

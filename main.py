import argparse
import base64

from aiohttp.web import Request, Response, Application, get, run_app
from aiohttp.client import ClientSession
from aiohttp.client_exceptions import InvalidURL
from icalendar import Calendar
from icalendar.cal import Event

parser = argparse.ArgumentParser("Calendar filter")
parser.add_argument("--port", type=int, default=8080)


class BaseDownloadError(Exception):
    """All download errors"""


class CalendarNotFound(BaseDownloadError):
    """Backing calendar was not found"""


class NotCalendar(BaseDownloadError):
    """Did not get a calendar back"""


class GenericDownloadError(BaseDownloadError):
    def __init__(self, status: int, reason: str | None):
        self.status = status
        self.reason = reason


async def download_ics(url: str) -> Calendar:
    async with ClientSession() as session:
        async with session.get(url) as response:
            if response.status == 404:
                raise CalendarNotFound()

            if response.status != 200:
                raise GenericDownloadError(
                    status=response.status,
                    reason=response.reason,
                )

            data = await response.text()
            try:
                cal = Calendar.from_ical(data)
            except ValueError:
                raise NotCalendar()

            return cal


async def handle(request: Request):
    path_parts = request.path.split("/")
    ics_url_b64 = path_parts[1]
    raw_excludes_b64 = path_parts[2]

    ics_url = base64.b64decode(ics_url_b64).decode("utf-8")
    raw_excludes = base64.b64decode(raw_excludes_b64).decode("utf-8").split(",")

    excludes = set((s.lower() for s in raw_excludes))

    if not ics_url:
        return Response(status=404, text="ics not specified")

    try:
        cal = await download_ics(ics_url)
    except GenericDownloadError as exc:
        return Response(status=exc.status, reason=exc.reason)
    except CalendarNotFound:
        return Response(status=404, reason="ICS calendar was not found")
    except NotCalendar:
        return Response(status=400, reason="Only calendar files are supported")
    except InvalidURL:
        return Response(status=400, reason="ICS URL was not valid")

    def should_include(item) -> bool:
        if not isinstance(item, Event):
            return True

        subject = "SUMMARY" in item and str(item["SUMMARY"]) or None
        if not subject:
            return True
        subject = subject.lower()
        if subject in excludes:
            return False

        return True

    new_components = [item for item in cal.subcomponents if should_include(item)]
    cal.subcomponents = new_components

    return Response(content_type="text/calendar", text=cal.to_ical().decode("utf-8"))


app = Application()
app.add_routes(
    [
        get("/{parts:.*}", handle),
    ]
)

if __name__ == "__main__":
    args = parser.parse_args()
    run_app(app, port=args.port)

import aiohttp
import asyncio
from xml.etree import ElementTree
from datetime import datetime
import time

from stib.stib import Network
from models import Heading, db
import peewee_async as pa


class StibApiError(Exception):
    pass


async def route_data(line, way):
    URL = 'http://m.stib.be/api/getitinerary.php?line={}&iti={}'

    if way not in (1, 2):
        raise ValueError("way must be an integer of value 1 or 2")
    line = str(line)
    if len(line) > 3:
        raise ValueError("line must not have more than 3 chars")

    url = URL.format(line, way)

    async with aiohttp.get(url) as response:
        if response.status != 200:
            raise StibApiError("HTTP Error :", response.status)
        return await response.read()


async def route_status(line, way, timeout=10):
    xml = await asyncio.wait_for(route_data(line, way), timeout)

    try:
        tree = ElementTree.fromstring(xml)
    except ElementTree.ParseError as e:
        raise StibApiError("Invalid XML") from e

    if tree.tag != "stops":
        raise StibApiError("Root tag shoud be 'stops' but is ", tree.tag)

    if tree.attrib['line'] != str(line) or tree.attrib['iti'] != str(way):
        raise StibApiError(
            "Response is not from queried line : we asked for line", line,
            "way", way, "and got line", tree.attrib['line'],
            "way", tree.attrib['iti']
        )

    stops = [stop for stop in tree if stop.tag == 'stop']
    output = []

    for stop in stops:
        has_vehicle = False
        for elem in stop:
            if elem.tag == 'present' and elem.text == 'TRUE':
                has_vehicle = True
                break
        output.append(has_vehicle)

    if output.count(True) > (len(output) / 2):
        raise StibApiError(
            "There is too much vehiclues on the line :",
            output.count(True), "for",
            len(output), "stops."
        )

    return output


async def save_route(line, way):
    try:
        route = await route_status(line, way)
    except StibApiError as e:
        print(e, (line, way))
        return None

    await pa.create_object(
        Heading, line=line,
        way=way, stops=route,
        timestamp=datetime.now()
    )

    await asyncio.sleep(20)
    save_route(line, way)


def main():
    loop = asyncio.get_event_loop()
    loop.run_until_complete(db.connect_async(loop=loop))

    network = Network()
    # we only need line numbers and we don't want Noctis
    lines = [line.id for line in network.lines if 'N' not in str(line.id)]
    routes = [(line, 1) for line in lines] + [(line, 2) for line in lines]
    routes = routes

    for line, way in routes:
        asyncio.async(save_route(line, way))

    loop.run_forever()


if __name__ == '__main__':
    main()

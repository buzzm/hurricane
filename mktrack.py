import pymongo
from pymongo import MongoClient
import datetime

import argparse
import sys

import json


codes = {
"C": "Closest approach to a coast, not followed by a landfall",
"G": "Genesis",
"I": "An intensity peak in terms of both pressure and wind",
"L": "Landfall (center of system crossing a coastline)",
"P": "Minimum in central pressure",
"R": "Provides additional detail on the intensity of the cyclone when rapid changes are underway",
"S": "Change of status of the system",
"T": "Provides additional detail on the track (position) of the cyclone",
"W": "Maximum sustained wind speed"
}



def process(cursor):
    fwrap = {"type": "FeatureCollection"}
    fcoll = []

    ptline = []

    n = 1
    for d in cursor:
        ff = {}
        ff['type'] = "Feature"

        bearing = -1
        if 'bearing' in d:
            bearing = d['bearing']

        maxWind = d['maxWind']
        if maxWind >= 157:
            color = "#ff605f"
        elif maxWind >= 130:
            color = "#ff8f20"
        elif maxWind >= 111:
            color = "#ffc140"
        elif maxWind >= 96:
            color = "#ffe775"
        elif maxWind >= 74:
            color = "#ffffcc"
        elif maxWind >= 39:
            color = "#01faf4"
        else:
            color = "#5ebaff"

        props = {
            "n": n,
            "ts": d['ts'].strftime("%Y-%m-%d %H:%M:%S"),
            "bearing": bearing,
            "windSpeed": maxWind,
            "pressure": d['minPres'],

            "marker-color": color,
            "marker-size": "small"
            }


        if d['code'] != 'D':
            props['code'] = d['code']
            props['info'] = codes[d['code']]

            props['marker-symbol'] = "circle"

        ff['properties'] = props



        pt = d['center']['coordinates']

        ptline.append(pt)

        ff['geometry'] = {"type":"Point", "coordinates": pt}

        fcoll.append(ff)

        n += 1

#        print d['code'], len(d['windRings']['properties'])
#         if d['code'] == 'L' and len(d['windRings']['properties']) > 1:
#             ff2 = {}
#             ff2['type'] = "Feature"
#             ff2['properties'] = {}
#             ff2['geometry'] = d['windRings']['geometries'][1]
#             fcoll.append(ff2)

            
        
    ff = {}
    ff['type'] = "Feature"
    ff['properties'] = {}
    ff['geometry'] = {
        "type":"LineString",
        "coordinates": ptline
        }
    fcoll.append(ff)

    fwrap['features'] = fcoll

    return fwrap




def go(rargs):
    client = MongoClient(host=rargs.host)
    db = client[rargs.db]
    coll = db[rargs.collection]

    name = rargs.name
    year = rargs.year

    c = coll.find({"$and": [ {"name":name}, {"ts":{"$gte": datetime.datetime(year,1,1)}}, {"ts":{"$lt": datetime.datetime(year+1,1,1)}} ] });

    fwrap = process(c)

    print json.dumps(fwrap)



def main(args):
    parser = argparse.ArgumentParser(description=
   """A util to dump a hurricane track to stdout in GeoJSON/FeatureCollection form.
   """,
         formatter_class=argparse.ArgumentDefaultsHelpFormatter
                                     )

    parser.add_argument('name', metavar='storm name',
                        help='storm name e.g. KATRINA')

    parser.add_argument('year', metavar='year',
                        type=int,
                        help='season of storm, e.g. 2005')

    parser.add_argument('--host',
                        metavar='mongoDBhost',
                        default="mongodb://localhost:27017",
                        help='connection string to server')

    parser.add_argument('--db',
                        metavar='db',
                        default="hurricane",
                        help='database to use')

    parser.add_argument('--collection', 
                        metavar='collectionName',
                        default="tracks",
                        help='name of collection to insert data')

    rargs = parser.parse_args()

    go(rargs)


if __name__ == "__main__":
    main(sys.argv)

import pymongo
from pymongo import MongoClient
import datetime

import argparse
import sys
import csv


def readHeader(reader):
    desc = None

    try:
        prow = [ x.strip() for x in next(reader) ]

        desc = {}

        desc['basin'] = prow[0][0:2]
        desc['nth'] = int(prow[0][2:4])

        # We will let the realstamp drive this.
        # desc['year'] = int(prow[0][4:8])

        if len(prow[1]) > 0:
            desc['name'] = prow[1]
        else:
            desc['name'] = "UNNAMED"

        desc['count'] = int(prow[2])

    except StopIteration:
        desc = None

    return desc


def llFromDistance(latitude, longitude, distance, bearing):
    # taken from: https://stackoverflow.com/a/46410871/13549 
    # distance in KM, bearing in degrees
    p = 0.017453292519943295     #Pi/180
    R = 6378.1  # // Radius of the Earth in KM

    brng = bearing * p  # // Convert bearing to radian
    lat = latitude * p  # // Current coords to radians
    lon = longitude * p

    #  Do the math magic
    lat = asin(sin(lat) * cos(distance / R) + cos(lat) * sin(distance / R) * cos(brng));
    lon = lon + (atan2(sin(brng) * sin(distance / R) * cos(lat), cos(distance / R) - sin(lat) * sin(lat)))

    #  Coords back to degrees and return
    #return [lat * (1/p), lon * (1/p)]
    return [lon * (1/p), lat * (1/p)]



def createPoly(center, quaddata):
    #  The 34/50/64 knot wind radii aren't "true" radii but they are a decent
    #  way to capture the (very!) rough polygon describing wind speed with just
    #  four integers!
    #  It kind of looks like this:
    #
    #             |
    #             a...
    #             |   ..
    #           . f     NE
    #         NW  |       .
    #        .    |       .
    # -------e----+----c--b-------
    #             |    .
    #             |  SE
    #             d.
    # 	          |
    #	          |
    #
    # An origin to NE value of 11 means just the NE quad has a 11 nautical
    # mile radius of 34 knot wind.  If SE is 6, then that quad has a smaller
    # "wedge."  Note that a quad can be missing (value 0 or -999) (SW above).
    # So ...
    # 1.  The wedges have some obvious abrupt changes at the boundaries.
    # 2.  You couldn't have NW and SE winds like above with *nothing* in the SW.
    # 3.  We want to use GeoJSON!
    # Approach:  Turn the quad data into an eight sided polygon.  The "diagonals"
    # i.e. NE and SW will be the given values and the compass directions will be
    # the AVERAGE of the 2 neighboringe extents!

    fudgeK = 2.0;

    pts = []

    nStart = (quaddata['NE'] + quaddata['NW'])/2.0
    eStart = (quaddata['NE'] + quaddata['SE'])/2.0
    sStart = (quaddata['SE'] + quaddata['SW'])/2.0
    wStart = (quaddata['SW'] + quaddata['NW'])/2.0

    x = center['coordinates'][1]
    y = center['coordinates'][0]

    pts.append(llFromDistance(x, y, nStart, 0))  # kickoff...

    d = quaddata['NE'] if quaddata['NE'] > 0 else (nStart+eStart)/fudgeK;
    mpt = llFromDistance(x, y, d, 45)
    pts.append(mpt)
    pts.append(llFromDistance(x, y, eStart, 90))

    d = quaddata['SE'] if quaddata['SE'] > 0 else (eStart+sStart)/fudgeK;
    mpt = llFromDistance(x, y, d, 135)
    pts.append(mpt)
    pts.append(llFromDistance(x, y, sStart, 180))

    d = quaddata['SW'] if quaddata['SW'] > 0 else (sStart+wStart)/fudgeK;
    mpt = llFromDistance(x, y, d, 225)
    pts.append(mpt)
    pts.append(llFromDistance(x, y, wStart, 270))

    d = quaddata['NW'] if quaddata['NW'] > 0 else (wStart+nStart)/fudgeK;
    mpt = llFromDistance(x, y, d, 315);
    pts.append(mpt)

    pts.append( llFromDistance(x, y, nStart, 0))  # close loop!

    return pts


def adjQuad(rr):
    something = False

    for q in ['NE','SE','SW','NW']:
        # Scrub out -999 
        rr[q] = max(0,rr[q])

        if(rr[q] > 0):  #something to do!
            something = True
            break

    if something is True:
        # Rescan and force any remaining zeros to .5:
        for q in ['NE','SE','SW','NW']:
            if rr[q] == 0:
                rr[q] = .5 

            # Incoming data is in nautical miles; must convert to KM:
            # 1 nm = 1.852 km
            rr[q] *= 1.852

    return something


def expandParent(parent, hole):
    for q in ['NE','SE','SW','NW']:
        if parent[q] - hole[q] < .5:
            parent[q] = hole[q] + .5 # add .5 KM            

def groomQuads(r34, r50, r64):
    result = 0

    # Start with r64...
    if adjQuad(r64):
        result = 64
        adjQuad(r50)
        adjQuad(r34)
        expandParent(r50, r64)
        expandParent(r34, r50)

    # Proceed to r50:
    elif adjQuad(r50):
        result = 50
        adjQuad(r34)
        expandParent(r34, r50)

    # Proceed to 364:
    elif adjQuad(r34):
        result = 34

    return result


def convertQuadData(center, r34, r50, r64):
    gwrap = {}
    gwrap['type'] = "GeometryCollection"

    gcoll = []
    gdesc = []

    gcoll.append(center)
    gdesc.append("center")

    result = groomQuads(r34, r50, r64)

    if 64 == result:
        r64_ring = createPoly(center, r64)
        r50_ring = createPoly(center, r50)
        r34_ring = createPoly(center, r34)
        gcoll.append({ "type":"MultiPolygon", "coordinates": [ [r64_ring], [r50_ring,r64_ring], [r34_ring,r50_ring] ] })

        gdesc.append("64knot winds")
        gdesc.append("50knot winds")
        gdesc.append("34knot winds")

    else:
        if 50 == result:
            r50_ring = createPoly(center, r50)
            r34_ring = createPoly(center, r34)
            gcoll.append({ "type":"MultiPolygon", "coordinates": [ [r50_ring], [r34_ring,r50_ring] ] })
            gdesc.append("50knot winds")
            gdesc.append("34knot winds")

        else:
            if 34 == result:
                r34_ring = createPoly(center, r34)
                gcoll.append({ "type":"MultiPolygon", "coordinates": [ [r34_ring] ] })
                gdesc.append("34knot winds")


    gwrap['geometries'] = gcoll
    gwrap['properties'] = gdesc

    return gwrap




def readData(reader):
    # No need to check for StopIteration because we know EXACTLY nany lines
    # we need to slurp
    prow = [ x.strip() for x in next(reader) ]
    
    data = {}
    #  DATA
#                                       max  min       34knt radii nmiles             50knt                     64knt
#date      time  X  s    lat     lon    knt  pres    NE    SE    SW    NW      NE
#20050823, 1800,  , TD, 23.1N,  75.1W,  30, 1008,    0,    0,    0,    0,      0,    0,    0,    0,      0,    0,    0,    0,
       
    # 200508231800
    ts = prow[0] + prow[1]
    data['ts'] = datetime.datetime.strptime(ts, "%Y%m%d%H%M")

    #  Invent the D code for regular data:
    data['code'] = prow[2] if prow[2] is not '' else 'D'

    data['status'] = prow[3];

    # lat long are X.XN or XX.XN    1 decimal place is good to 11.1 km, or about 6.8 miles.  Fine!
    lat = float(prow[4][:-1])
    if prow[4][-1] == 'S':
        lat = lat * -1.0
    lon = float(prow[5][:-1])
    if prow[5][-1] == 'W':
        lon = lon * -1.0
        
    data['maxWind'] = int(prow[6])
    data['minPres'] = int(prow[7])

    data['center'] = { "type":"Point", "coordinates": [lon,lat] }

    data['windRadii'] = {
        "R34":{"NE": int(prow[8]), "SE": int(prow[9]), "SW": int(prow[10]), "NW": int(prow[11]) },
        "R50":{"NE": int(prow[12]), "SE": int(prow[13]), "SW": int(prow[14]), "NW": int(prow[15]) },
        "R64":{"NE": int(prow[16]), "SE": int(prow[17]), "SW": int(prow[18]), "NW": int(prow[19]) }
        }

    # Send them all over again; we may have to groom the values...
    gwrap = convertQuadData(data['center'],
        {"NE": int(prow[8]), "SE": int(prow[9]), "SW": int(prow[10]), "NW": int(prow[11]) },
        {"NE": int(prow[12]), "SE": int(prow[13]), "SW": int(prow[14]), "NW": int(prow[15]) },
        {"NE": int(prow[16]), "SE": int(prow[17]), "SW": int(prow[18]), "NW": int(prow[19]) }
        )

    data['windRings'] = gwrap;

    return data



from math import cos, sin, asin, atan2, sqrt, degrees, radians

def distance(lat1, lon1, lat2, lon2):
    p = 0.017453292519943295     # Pi/180
    a = 0.5 - cos((lat2 - lat1) * p)/2 + cos(lat1 * p) * cos(lat2 * p) * (1 - cos((lon2 - lon1) * p)) / 2
    return 12742 * asin(sqrt(a)) # 2 * Radiusofearth * asin...


def bearing(endlat, endlon, startlat, startlon):
    endlat = radians(endlat)
    startlat = radians(startlat)

    diffLong = radians(endlon - startlon)

    x = sin(diffLong) * cos(startlat)
    y = cos(endlat) * sin(startlat) - (sin(endlat)
            * cos(startlat) * cos(diffLong))

    initial_bearing = atan2(x, y)

    # Now we have the initial bearing but atan2 return values
    # from -180 to + 180 which is not what we want for a compass bearing
    # The solution is to normalize the initial bearing as shown below
    initial_bearing = degrees(initial_bearing)
    compass_bearing = (initial_bearing + 360) % 360

    return compass_bearing


def go(rargs):
    client = MongoClient(host=rargs.host)

    db = client[rargs.db]

    coll = db[rargs.collection]

    fname = rargs.fname

    n = 0

    with open(fname, 'r') as csvfile:
        reader = csv.reader(csvfile)

        tot = 0

        if rargs.drop == True:
            coll.drop()

        while True:
            info = readHeader(reader)
            if info is None:
                break

            maxn = info['count']

            items = []
            for n in range(0, maxn):
                items.append(readData(reader))

            for n in range(0, maxn):
                a = items[n]
                if(n < maxn - 1):
                    b = items[n+1]

                    tdelta = b['ts'] - a['ts']

                    # Distance between two doesn't matter....
                    dist = distance(a['center']['coordinates'][1], a['center']['coordinates'][0], 
                                    b['center']['coordinates'][1], b['center']['coordinates'][0])

                    # ... but for bearing, it does!  Otherwise you're going backwards.
                    cbear = bearing(b['center']['coordinates'][1], b['center']['coordinates'][0], 
                                    a['center']['coordinates'][1], a['center']['coordinates'][0])

                    b['bearing'] = int(round(cbear))

                    if tdelta.seconds != 0:
                        b['avgSpeed'] = int(round(dist / (tdelta.seconds / 3600.0)))


            for n in range(0, maxn):
                items[n]['basin'] = info['basin']
                items[n]['nth'] = info['nth']
                items[n]['name'] = info['name']
                
                coll.insert(items[n])
            

            tot += 1
            if 0 == tot % 100:
                print tot


        print "total events loaded:", tot

        print "creating 2dsphere index on center..."
        coll.create_index([("center","2dsphere")])

        print "creating 2dsphere index on windRings..."
        coll.create_index([("windRings","2dsphere")])



def main(args):
    parser = argparse.ArgumentParser(description=
   """A quick util to load HURDAT2 data into MongoDB
   """,
         formatter_class=argparse.ArgumentDefaultsHelpFormatter
   )
    parser.add_argument('fname', metavar='fileName',
                   help='file to load')

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

    parser.add_argument('--drop', 
                   action='store_true',
                   help='drop target collection before loading')

    rargs = parser.parse_args()

    go(rargs)




if __name__ == "__main__":
    main(sys.argv)


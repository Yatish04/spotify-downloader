#!/usr/bin/env python
# -*- coding: UTF-8 -*-

from core import metadata
from core import convert
from core import misc
from core.logger import log
from bs4 import BeautifulSoup
from titlecase import titlecase
from slugify import slugify
import spotipy
import pafy
import urllib.request
import os
import time
import sys


def generate_songname(tags):
    """Generate a string of the format '[artist] - [song]' for the given spotify song."""
    raw_song = u'{0} - {1}'.format(tags['artists'][0]['name'], tags['name'])
    return raw_song


def generate_metadata(raw_song):
    """Fetch a song's metadata from Spotify."""
    if misc.is_spotify(raw_song):
        # fetch track information directly if it is spotify link
        meta_tags = spotify.track(raw_song)
    else:
        # otherwise search on spotify and fetch information from first result
        try:
            meta_tags = spotify.search(raw_song, limit=1)['tracks']['items'][0]
        except IndexError:
            return None
    artist = spotify.artist(meta_tags['artists'][0]['id'])
    album = spotify.album(meta_tags['album']['id'])

    try:
        meta_tags[u'genre'] = titlecase(artist['genres'][0])
    except IndexError:
        meta_tags[u'genre'] = None
    try:
        meta_tags[u'copyright'] = album['copyrights'][0]['text']
    except IndexError:
        meta_tags[u'copyright'] = None
    try:
        meta_tags[u'external_ids'][u'isrc']
    except KeyError:
        meta_tags[u'external_ids'][u'isrc'] = None

    meta_tags[u'release_date'] = album['release_date']
    meta_tags[u'publisher'] = album['label']
    meta_tags[u'total_tracks'] = album['tracks']['total']

    return meta_tags


def is_video(result):
    # ensure result is not a channel
    not_video = result.find('channel') is not None or \
                'yt-lockup-channel' in result.parent.attrs['class'] or \
                'yt-lockup-channel' in result.attrs['class']

    # ensure result is not a mix/playlist
    not_video = not_video or \
               'yt-lockup-playlist' in result.parent.attrs['class']

    # ensure video result is not an advertisement
    not_video = not_video or \
                result.find('googleads') is not None

    video = not not_video
    return video


def generate_youtube_url(raw_song, meta_tags, tries_remaining=5):
    """Search for the song on YouTube and generate a URL to its video."""
    # prevents an infinite loop but allows for a few retries
    if tries_remaining == 0:
        return

    if meta_tags is None:
        song = raw_song
        search_url = misc.generate_search_url(song, viewsort=False)
    else:
        song = generate_songname(meta_tags)
        search_url = misc.generate_search_url(song, viewsort=True)

    item = urllib.request.urlopen(search_url).read()
    items_parse = BeautifulSoup(item, "html.parser")

    videos = []
    for x in items_parse.find_all('div', {'class': 'yt-lockup-dismissable yt-uix-tile'}):

        if not is_video(x):
            continue

        y = x.find('div', class_='yt-lockup-content')
        link = y.find('a')['href']
        title = y.find('a')['title']

        try:
            videotime = x.find('span', class_="video-time").get_text()
        except AttributeError:
            return generate_youtube_url(raw_song, meta_tags, tries_remaining - 1)

        youtubedetails = {'link': link, 'title': title, 'videotime': videotime,
                          'seconds': misc.get_sec(videotime)}
        videos.append(youtubedetails)
        if meta_tags is None:
            break

    if not videos:
        return None

    if args.manual:
        log.info(song)
        log.info('0. Skip downloading this song.\n')
        # fetch all video links on first page on YouTube
        for i, v in enumerate(videos):
            log.info(u'{0}. {1} {2} {3}'.format(i+1, v['title'], v['videotime'],
                  "http://youtube.com"+v['link']))
        # let user select the song to download
        result = misc.input_link(videos)
        if result is None:
            return None
    else:
        if meta_tags is not None:
            # filter out videos that do not have a similar length to the Spotify song
            duration_tolerance = 10
            max_duration_tolerance = 20
            possible_videos_by_duration = list()

            '''
            start with a reasonable duration_tolerance, and increment duration_tolerance
            until one of the Youtube results falls within the correct duration or
            the duration_tolerance has reached the max_duration_tolerance
            '''
            while len(possible_videos_by_duration) == 0:
                possible_videos_by_duration = list(filter(lambda x: abs(x['seconds'] - (int(meta_tags['duration_ms'])/1000)) <= duration_tolerance, videos))
                duration_tolerance += 1
                if duration_tolerance > max_duration_tolerance:
                    log.error("{0} by {1} was not found.\n".format(meta_tags['name'],meta_tags['artists'][0]['name']))
                    return None

            result = possible_videos_by_duration[0]
        else:
            # if the metadata could not be acquired, take the first result
            # from Youtube because the proper song length is unknown
            result = videos[0]

    full_link = None
    if result:
        full_link = u'youtube.com{0}'.format(result['link'])

    return full_link


def go_pafy(raw_song, meta_tags):
    """Parse track from YouTube."""
    if misc.is_youtube(raw_song):
        track_info = pafy.new(raw_song)
    else:
        track_url = generate_youtube_url(raw_song, meta_tags)

        if track_url is None:
            track_info = None
        else:
            track_info = pafy.new(track_url)

    return track_info


def get_youtube_title(content, number=None):
    """Get the YouTube video's title."""
    title = content.title
    if number is None:
        return title
    else:
        return '{0}. {1}'.format(number, title)


def feed_playlist(username):
    """Fetch user playlists when using the -u option."""
    playlists = spotify.user_playlists(username)
    links = []
    check = 1

    while True:
        for playlist in playlists['items']:
            # in rare cases, playlists may not be found, so playlists['next']
            # is None. Skip these. Also see Issue #91.
            if playlist['name'] is not None:
                log.info(u'{0:>5}. {1:<30}  ({2} tracks)'.format(
                    check, playlist['name'],
                    playlist['tracks']['total']))
                links.append(playlist)
                check += 1
        if playlists['next']:
            playlists = spotify.next(playlists)
        else:
            break

    playlist = misc.input_link(links)
    write_playlist(playlist['owner']['id'], playlist['id'])


def write_tracks(text_file, tracks):
    with open(text_file, 'a') as file_out:
        while True:
            for item in tracks['items']:
                if 'track' in item:
                    track = item['track']
                else:
                    track = item
                try:
                    file_out.write(track['external_urls']['spotify'] + '\n')
                except KeyError:
                    print(u'Skipping track {0} by {1} (local only?)'.format(
                        track['name'], track['artists'][0]['name']))
            # 1 page = 50 results
            # check if there are more pages
            if tracks['next']:
                tracks = spotify.next(tracks)
            else:
                break


def write_playlist(username, playlist_id):
    results = spotify.user_playlist(username, playlist_id,
                                    fields='tracks,next,name')
    text_file = u'{0}.txt'.format(slugify(results['name'], ok='-_()[]{}'))
    log.info(u'writing {0} tracks to {1}'.format(
               results['tracks']['total'], text_file))
    tracks = results['tracks']
    write_tracks(text_file, tracks)


def write_album(album):
    tracks = spotify.album_tracks(album['id'])
    text_file = u'{0}.txt'.format(slugify(album['name'], ok='-_()[]{}'))
    log.info(u'writing {0} tracks to {1}'.format(
               tracks['total'], text_file))
    write_tracks(text_file, tracks)


def download_song(file_name, content):
    """Download the audio file from YouTube."""
    if args.input_ext == '.webm':
        link = content.getbestaudio(preftype='webm')
    elif args.input_ext == '.m4a':
        link = content.getbestaudio(preftype='m4a')
    else:
        return False

    if link is None:
        return False
    else:
        filepath = '{0}{1}'.format(os.path.join(args.folder, file_name),
                                   args.input_ext)
        link.download(filepath=filepath)
        return True


def check_exists(music_file, raw_song, meta_tags, islist=True):
    """Check if the input song already exists in the given folder."""
    songs = os.listdir(args.folder)
    for song in songs:
        if song.endswith('.temp'):
            os.remove(os.path.join(args.folder, song))
            continue
        # check if any song with similar name is already present in the given folder
        file_name = misc.sanitize_title(music_file)
        if song.startswith(file_name):
            # check if the already downloaded song has correct metadata
            already_tagged = metadata.compare(os.path.join(args.folder, song), meta_tags)

            # if not, remove it and download again without prompt
            if misc.is_spotify(raw_song) and not already_tagged:
                os.remove(os.path.join(args.folder, song))
                return False

            # do not prompt and skip the current song
            # if already downloaded when using list
            if islist:
                log.warning('Song already exists')
                return True
            # if downloading only single song, prompt to re-download
            else:
                prompt = input('Song with same name has already been downloaded. '
                               'Re-download? (y/N): ').lower()
                if prompt == 'y':
                    os.remove(os.path.join(args.folder, song))
                    return False
                else:
                    return True
    return False


def grab_list(text_file):
    """Download all songs from the list."""
    with open(text_file, 'r') as listed:
        lines = (listed.read()).splitlines()
    # ignore blank lines in text_file (if any)
    try:
        lines.remove('')
    except ValueError:
        pass
    log.info(u'Preparing to download {} songs\n'.format(len(lines)))
    number = 1

    for raw_song in lines:
        try:
            grab_single(raw_song, number=number)
            print('')
        # token expires after 1 hour
        except spotipy.client.SpotifyException:
            # refresh token when it expires
            new_token = misc.generate_token()
            global spotify
            spotify = spotipy.Spotify(auth=new_token)
            grab_single(raw_song, number=number)
        # detect network problems
        except (urllib.request.URLError, TypeError, IOError):
            lines.append(raw_song)
            # remove the downloaded song from file
            misc.trim_song(text_file)
            # and append it at the end of file
            with open(text_file, 'a') as myfile:
                myfile.write(raw_song + '\n')
            log.warning('Failed to download song. Will retry after other songs\n')
            print('')
            # wait 0.5 sec to avoid infinite looping
            time.sleep(0.5)
            continue
        except KeyboardInterrupt as e:
            misc.grace_quit(e)

        misc.trim_song(text_file)
        number += 1


def grab_playlist(playlist):
    if '/' in playlist:
        if playlist.endswith('/'):
            playlist = playlist[:-1]
        splits = playlist.split('/')
    else:
        splits = playlist.split(':')

    try:
        username = splits[-3]
    except IndexError:
        # Wrong format, in either case
        log.error('The provided playlist URL is not in a recognized format!')
        sys.exit(10)
    playlist_id = splits[-1]
    try:
        write_playlist(username, playlist_id)
    except spotipy.client.SpotifyException:
        log.error('Unable to find playlist')
        log.info('Make sure the playlist is set to publicly visible and then try again')
        sys.exit(11)


def grab_album(album):
    if '/' in album:
        if album.endswith('/'):
            playlist = playlist[:-1]
        splits = album.split('/')
    else:
        splits = album.split(':')

    album_id = splits[-1]
    album = spotify.album(album_id)

    write_album(album)


def grab_single(raw_song, number=None):
    """Logic behind downloading a song."""
    if number:
        islist = True
    else:
        islist = False

    if misc.is_youtube(raw_song):
        meta_tags = generate_metadata(raw_song)
        content = go_pafy(raw_song, meta_tags)
        raw_song = slugify(content.title).replace('-', ' ')

    meta_tags = generate_metadata(raw_song)
    content = go_pafy(raw_song, meta_tags)
    if content is None:
        return

    # print '[number]. [artist] - [song]' if downloading from list
    # otherwise print '[artist] - [song]'
    log.info(get_youtube_title(content, number))
    # generate file name of the song to download
    songname = content.title

    if meta_tags is not None:
        refined_songname = generate_songname(meta_tags)
        if not refined_songname == ' - ':
            songname = refined_songname

    file_name = misc.sanitize_title(songname)

    if not check_exists(file_name, raw_song, meta_tags, islist=islist):
        if download_song(file_name, content):
            input_song = file_name + args.input_ext
            output_song = file_name + args.output_ext
            print('')
            convert.song(input_song, output_song, args.folder,
                         avconv=args.avconv, verbose=args.verbose)
            if not args.input_ext == args.output_ext:
                os.remove(os.path.join(args.folder, input_song))

            if not args.no_metadata:
                metadata.embed(os.path.join(args.folder, output_song), meta_tags)
        else:
            log.error('No audio streams available')


class TestArgs(object):
    manual = False
    input_ext = '.m4a'
    output_ext = '.mp3'
    folder = 'Music/'


# token is mandatory when using Spotify's API
# https://developer.spotify.com/news-stories/2017/01/27/removing-unauthenticated-calls-to-the-web-api/
token = misc.generate_token()
spotify = spotipy.Spotify(auth=token)

if __name__ == '__main__':
    args = misc.get_arguments()
    misc.filter_path(args.folder)

    if args.song:
        grab_single(raw_song=args.song)
    elif args.list:
        grab_list(text_file=args.list)
    elif args.playlist:
        grab_playlist(playlist=args.playlist)
    elif args.album:
        grab_album(album=args.album)
    elif args.username:
        feed_playlist(username=args.username)
else:
    misc.filter_path('Music')
    args = TestArgs()

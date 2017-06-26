# -*- coding: UTF-8 -*-

import spotdl

username = 'alex'

def test_user():
    expect_playlists = 7
    playlists = spotdl.spotify.user_playlists(username)
    playlists = len(playlists['items'])
    assert playlists == expect_playlists

def test_playlist():
    expect_tracks = 14
    playlist = spotdl.spotify.user_playlists(username)['items'][0]
    tracks = playlist['tracks']['total']
    assert tracks == expect_tracks

def test_list():
    playlist = spotdl.spotify.user_playlists(username)['items'][0]
    expect_lines = playlist['tracks']['total']
    result = spotdl.spotify.user_playlist(playlist['owner']['id'], playlist['id'], fields='tracks,next')
    tracks = result['tracks']
    spotdl.misc.feed_tracks('list.txt', tracks)

    while tracks['next']:
        tracks = spotdl.spotify.next(tracks)
        spotdl.misc.feed_tracks('list.txt', tracks)

    with open('list.txt', 'r') as listed:
        expect_song = (listed.read()).splitlines()[0]

    spotdl.misc.trim_song('list.txt')
    with open('list.txt', 'a') as myfile:
        myfile.write(expect_song)

    with open('list.txt', 'r') as listed:
        songs = (listed.read()).splitlines()

    lines = len(songs)
    song = songs[-1]
    assert (expect_lines == lines and expect_song == song)
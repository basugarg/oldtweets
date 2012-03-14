#!/usr/bin/env python
# encoding: utf-8
"""
READ ME FIRST!

This script is a way to back up (and delete, if you so desire) all your tweets
beyond the latest 50

This script will work if, and only if, you:

1/ Install required libs (via pip -r requirements.txt)
2/ go to dev.twitter.com, sign up with your account and create a new app
(the details can be bogus, your app will be private)
3/ copy the consumer key and secret from your app in a credentials file
4/ go to "my access token" in the (righthand) menu of your app and copy
the token and key in a credentials file
(a credentials file is distributed with this script, as a sample)

"""
import os
import re
import time
import twitter
import sys
import getopt
import math
import string
import httplib
import urlparse
import socket
from cgi import escape
from datetime import datetime
from urllib import quote_plus
from logbook import Logger

log = Logger("oldtweets")

help_message = '''
oldtweets.py - backup or delete your older tweets
Based on a script by David Larlet @davidbgk

** run it to see the output
cat credentials | ./oldtweets.py

** Want to delete old tweets?
cat credentials | ./oldtweets.py --delete

** By default, the script will ignore the latests 50 tweets.
Want to choose another number (will be rounded down to the closest half hundred)
cat credentials | ./oldtweets.py --keep=200

'''

TWEETS_PATH = '/Users/david/Sites/larlet/larlet.fr/david/stream/tweets/'
SCREEN_NAME = 'davidbgk'

class URLExpander:
    """
    Stolen from http://the.taoofmac.com/space/blog/2009/08/10/2205
    """
    # known shortening services
    shorteners = ['tr.im','is.gd','tinyurl.com','bit.ly','snipurl.com','cli.gs',
                  't.co', 'bgk.me', 'feedproxy.google.com','feeds.arstechnica.com']
    # learned hosts
    learned = []

    def resolve(self, url, components):
        """ Try to resolve a single URL """
        c = httplib.HTTPConnection(components.netloc)
        c.request("GET", components.path)
        r = c.getresponse()
        l = r.getheader('Location')
        if l == None:
            return url # it might be impossible to resolve, so best leave it as is
        else:
            return l

    def query(self, url, recurse = True):
        """ Resolve a URL """
        components = urlparse.urlparse(url)
        # Check known shortening services first
        if components.netloc in self.shorteners:
            return self.resolve(url, components)
        # If we haven't seen this host before, ping it, just in case
        if components.netloc not in self.learned:
            ping = self.resolve(url, components)
            if ping != url:
                self.shorteners.append(components.netloc)
                self.learned.append(components.netloc)
                return ping
        # The original URL was OK
        return url

url_expander = URLExpander()

def __urlize(text, trim_url_limit=None, nofollow=False, autoescape=False):
    """
    Converts any URLs in text into clickable links.

    Works on http://, https://, www. links and links ending in .org, .net or
    .com. Links can have trailing punctuation (periods, commas, close-parens)
    and leading punctuation (opening parens) and it'll still do the right
    thing.

    If trim_url_limit is not None, the URLs in link text longer than this limit
    will truncated to trim_url_limit-3 characters and appended with an elipsis.

    If nofollow is True, the URLs in link text will get a rel="nofollow"
    attribute.

    If autoescape is True, the link text and URLs will get autoescaped.

    Stolen from Django, useful to retrieve short URLs and expand those.
    """
    LEADING_PUNCTUATION  = ['(', '<', '&lt;']
    TRAILING_PUNCTUATION = ['.', ',', ')', '>', '\n', '&gt;']
    word_split_re = re.compile(r'(\s+)')
    punctuation_re = re.compile('^(?P<lead>(?:%s)*)(?P<middle>.*?)(?P<trail>(?:%s)*)$' % \
        ('|'.join([re.escape(x) for x in LEADING_PUNCTUATION]),
        '|'.join([re.escape(x) for x in TRAILING_PUNCTUATION])))

    trim_url = lambda x, limit=trim_url_limit: limit is not None and (len(x) > limit and ('%s...' % x[:max(0, limit - 3)])) or x
    safe_input = True
    words = word_split_re.split(text)
    for i, word in enumerate(words):
        match = None
        if '.' in word or '@' in word or ':' in word:
            match = punctuation_re.match(word)
        if match:
            lead, middle, trail = match.groups()
            # Make URL we want to point to.
            url = None
            middle = middle.strip(u'”').encode("utf-8")  # Custom
            if middle.startswith('http://') or middle.startswith('https://'):
                url = quote_plus(middle, safe='/&=:;#?+*')
            elif middle.startswith('www.') or ('@' not in middle and \
                    middle and middle[0] in string.ascii_letters + string.digits and \
                    (middle.endswith('.org') or middle.endswith('.net') or middle.endswith('.com'))):
                url = quote_plus('http://%s' % middle, safe='/&=:;#?+*')
            # Make link.
            if url:
                trimmed = trim_url(middle)
                if autoescape and not safe_input:
                    lead, trail = escape(lead), escape(trail)
                    url, trimmed = escape(url), escape(trimmed)
                middle = url_expander.query(url)  # Custom
                words[i] = u'%s%s%s' % (lead, middle, trail)
            else:
                if safe_input:
                    words[i] = word
                elif autoescape:
                    words[i] = escape(word)
        elif safe_input:
            words[i] = word
        elif autoescape:
            words[i] = escape(word)
    return u''.join(words)


class Usage(Exception):
    def __init__(self, msg):
        self.msg = msg


def main(argv=None):
    option_delete = False
    keep_number = 50
    if argv is None:
        argv = sys.argv
    try:
        try:
            opts, args = getopt.getopt(argv[1:], "h:v", ["delete", "help", "keep="])
        except getopt.error, msg:
            raise Usage(msg)

        # option processing
        for option, value in opts:
            if option in ("-h", "--help"):
                raise Usage(help_message)
            if option == "--delete":
                option_delete = True
            if option == "--keep":
                try:
                    keep_number = int(value)
                except:
                    raise Usage("Value of --keep must be a number. Ideally a multiple of 50")


    except Usage, err:
        print >> sys.stderr, sys.argv[0].split("/")[-1] + ": " + str(err.msg)
        print >> sys.stderr, "\t for help use --help"
        return 2

    params = dict(line.split() for line in sys.stdin.readlines())
    api = twitter.Api(**params)

    min_page = int(math.floor(keep_number/50))
    existing_tweets_id = [filename[:-4] for filename in os.listdir(TWEETS_PATH)]
    for i in range(min_page, min_page+50):
        log.info(u"Fetching page: %s" % i)
        statuses = api.GetUserTimeline(page=i+1, count=49)
        if not statuses:
            break
        for status in statuses:
            tweet = status.AsDict()
            tweet_id = str(tweet['id'])
            if tweet_id not in existing_tweets_id:
                log.debug(u"Processing tweet: %s" % tweet_id)
                if tweet['user']['screen_name']==SCREEN_NAME and not tweet['retweeted']:
                    created_at = datetime.strptime(tweet['created_at'], "%a %b %d %H:%M:%S +0000 %Y")
                    retweet_count = 'retweet_count' in tweet and tweet['retweet_count'] or u'0'
                    log.debug(u"Urlizing content: %s" % tweet['text'])
                    try:
                        content = __urlize(tweet['text'])
                    except socket.gaierror:
                        content = tweet['text']
                        log.error(u"Error urlizing: %s" % content)
                        log.error(u"Verify the tweet online: https://twitter.com/%s/status/%s" % (SCREEN_NAME, tweet_id))
                    except socket.error:  # couldn't figure out the difference easily
                        content = tweet['text']
                        log.error(u"Alternative error urlizing: %s" % content)
                        log.error(u"Verify the tweet online: https://twitter.com/%s/status/%s" % (SCREEN_NAME, tweet_id))
                    text =  u'%s$%s$%s\n%s' % (tweet_id, created_at, retweet_count, content)
                    open(TWEETS_PATH+tweet_id+'.txt', 'w').write(text.encode('utf-8'))
                    time.sleep(0.1) # throttled api + urlize
                else:
                    log.info(u"Ownership concern, check: https://twitter.com/%s/status/%s" % (SCREEN_NAME, tweet_id))
            else:
                log.debug(u"Already fetched tweet: %s" % tweet_id)
                if option_delete:
                    try:
                        api.DestroyStatus(tweet_id)
                        log.debug(u"Tweet deleted: %s" % tweet_id)
                        time.sleep(0.1) # throttled api
                    except twitter.TwitterError, e:
                        log.error(u"Tweet NOT deleted: %s %s %s" % (tweet_id, tweet, e))


if __name__ == "__main__":
    sys.exit(main())

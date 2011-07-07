#!/usr/bin/env python
from SocketServer import TCPServer, ThreadingMixIn, StreamRequestHandler
from digg.api import Digg
from time import time
from urlparse import urlparse
import simplejson as json
import textwrap
import urllib
import re

digg = Digg()
ADDRESS = 'synack.me\t70'
htmlpattern = re.compile('<[^>]+>')

def clean_text(text, indent=0, wrap=72):
    delim = '\r\n' + ('    ' * indent)
    text = text.encode('ascii', 'ignore')
    text = htmlpattern.sub('', text)
    text = textwrap.wrap(text, wrap)
    text = delim.join(text)
    return text

def shorturl(url):
    res = urllib.urlopen('http://is.gd/api.php?longurl=' + url)
    return res.read().strip('\r\n\t ')


class ThreadedTCPServer(ThreadingMixIn, TCPServer):
    allow_reuse_address = True

class GopherHandler(StreamRequestHandler):
    def __init__(self, request, client_address, server):
        StreamRequestHandler.__init__(self, request, client_address, server)

    def handle(self):
        self.sites = {
            'digg': DiggSite(self),
            'hackernews': HNSite(self),
        }

        line = self.rfile.readline().rstrip('\r\n')

        log = file('/home/synack/src/news-gopher/access.log', 'a+')
        log.write('%s %i %s\n' % (self.client_address[0], int(time()), line))
        log.close()

        if line == '' or line == '-)':
            self.handle_index()
            return

        site = line.split('/')[0]
        if site in self.sites:
            self.sites[site].handle(line)
        else:
            self.handle_notfound(line)

    def handle_index(self):
        #self.wfile.write(file('motd.txt', 'r').read())

        for site in self.sites:
            self.wfile.write('1%s\t%s/\t%s\r\n' % (site, site, ADDRESS))
        self.wfile.write('.\r\n')

    def handle_notfound(self, line):
        print 'GopherHandler.handle_notfound', repr(line)
        return


class Site(object):
    def __init__(self, handler):
        self.handler = handler

    def write(self, data):
        self.handler.wfile.write(data)

    def handle(self, line):
        pass

    def handle_notfound(self, line):
        print 'Site.handle_notfound', repr(line)
        return


class HNSite(Site):
    def __init__(self, *args, **kwargs):
        Site.__init__(self, *args, **kwargs)

        self.pages = {
            'frontpage.list': self.page_frontpage,
            'ask.list': self.page_ask,
            'new.list': self.page_new,
        }

    def request(self, path):
        res = urllib.urlopen('http://api.ihackernews.com' + path)
        return json.loads(res.read())

    def handle(self, line):
        print 'HNHandler.handle', repr(line)
        line = line.split('/', 1)[1]

        if line == '':
            self.handle_index()

        if line.endswith('.story'):
            self.handle_story(line)
            return

        if line in self.pages:
            self.pages[line]()
            return

    def handle_index(self):
        self.write(file('/home/synack/src/news-gopher/motd/hn.txt', 'r').read())

        for page in ('frontpage', 'new', 'ask'):
            self.write('1%s\thackernews/%s.list\t%s\r\n' % (page, page, ADDRESS))
        self.write('.\r\n')

    def page_frontpage(self):
        self.page('/page')

    def page_ask(self):
        self.page('/ask')

    def page_new(self):
        self.page('/new')

    def page(self, endpoint):
        data = self.request(endpoint)
        for story in data['items']:
            self.write('0%s\thackernews/%s.story\t%s\r\ni%s\r\ni%i points - %i comments\r\n\r\n' % (
                story['title'].encode('ascii', 'replace'),
                story['id'],
                ADDRESS,
                urlparse(story['url']).netloc,
                story['points'],
                story['commentCount']))
        self.write('.\r\n')

    def handle_story(self, line):
        id = line.rsplit('.', 1)[0]
        post = self.request('/post/' + id)

        self.write('%s\r\n%s -- %s\r\n%i points by %s %s\r\n%i comments\r\n\r\n%s\r\n' % (
            post['title'].encode('ascii', 'replace'),
            urlparse(post['url']).netloc,
            shorturl(post['url']),
            post['points'],
            post['postedBy'],
            post['postedAgo'],
            post['commentCount'],
            clean_text(post.get('text', ''))))

        self.write('\r\nComments\r\n' + ('-' * 72) + '\r\n')

        for comment in post['comments']:
            self.write_comment(comment)

    
    def write_comment(self, comment, indent=0):
        space = '    ' * indent
        wrap = 72 - (indent * 4)
        self.write('%s%i points by %s %s\r\n%s%s\r\n' % (
            space,
            comment['points'],
            comment['postedBy'],
            comment['postedAgo'],
            space, clean_text(comment['comment'], indent, wrap)))
        self.write(space + ('-' * wrap) + '\r\n')

        for comment in comment.get('children', []):
            self.write_comment(comment, indent + 1)

class DiggSite(Site):
    def handle(self, line=None):
        print 'DiggHandler.handle', repr(line)
        line = line.split('/', 1)[1]

        if line == '':
            self.handle_index()
        
        if line.endswith('.list'):
            self.handle_storylist(line)
            return

        if line.endswith('.story'):
            self.handle_story(line)
            return

        self.handle_notfound(line)

    def handle_index(self):
        self.write(file('/home/synack/src/news-gopher/motd/digg.txt', 'r').read())

        topics = digg.topic.getAll()['topics']

        for topic in topics:
            self.write('1%s\tdigg/%s.list\t%s\r\n' % (topic['name'], topic['short_name'], ADDRESS))
        self.write('.\r\n')

    def handle_storylist(self, topic):
        topic = topic.rsplit('.')[0]
        for story in digg.story.getPopular(topic=topic)['stories']:
            self.write('0%s\tdigg/%s/%s.story\t%s\r\ni%i diggs - %i comments\r\ni%s\r\n\r\n' % (
                story['title'].encode('ascii', 'replace'),
                story['topic']['short_name'],
                story['id'],
                ADDRESS,
                story['diggs'],
                story['comments'],
                story['description'].encode('ascii', 'replace')))

        self.write('.\r\n')

    def handle_story(self, story):
        id = story.rsplit('/', 1)[1].rsplit('.', 1)[0]
        story = digg.story.getInfo(story_id=id)['stories'][0]
        comments = digg.story.getComments(story_id=id)['comments']

        self.write('%s\r\n%s\r\n%i diggs - %i comments\r\n\r\n%s\r\n\r\n' % (
            story['title'].encode('ascii', 'replace'),
            story['link'],
            story['diggs'],
            story['comments'],
            story['description'].encode('ascii', 'replace')))

        self.write('Comments\r\n' + ('-' * 72) + '\r\n')

        for comment in comments:
            self.write('%i diggs, %i buries\r\n%s\r\n' % (
                comment['up'],
                comment['down'],
                comment['content'].encode('ascii', 'replace')))
            self.write(('-' * 72) + '\r\n')

        self.write('.\r\n')

if __name__ == '__main__':
    server = ThreadedTCPServer(('0.0.0.0', 70), GopherHandler)
    server.serve_forever()

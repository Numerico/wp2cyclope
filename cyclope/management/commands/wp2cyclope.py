from django.core.management.base import BaseCommand, CommandError
from optparse import make_option
import mysql.connector
from cyclope.models import SiteSettings
import re
from cyclope.apps.articles.models import Article

class Command(BaseCommand) :
    help = """Migrates a site in WordPress to Cyclope CMS.
    Requires the options server, database and user, passphrase is optional.
    Optional WordPress table prefix option, defaults to 'wp_'."""

    #NOTE django > 1.8 uses argparse instead of optparse module, 
    #so "You are encouraged to exclusively use **options for new commands."
    #https://docs.djangoproject.com/en/1.9/howto/custom-management-commands/
    option_list = BaseCommand.option_list + (
        make_option('--server',
            action='store',
            dest='server',
            default=None,
            help='WP-Site Host Name.'
        ),
        make_option('--user',
            action='store',
            dest='user',
            default=None,
            help='Database User.'
        ),
        make_option('--password',
            action='store',
            dest='password',
            default=None,
            help='Database Password.'
        ),
        make_option('--database',
            action='store',
            dest='db',
            default=None,
            help='Database name.'
        ),
        make_option('--table_prefix',
            action='store',
            dest='wp_prefix',
            default='wp_',
            help='Wordpress DB Table Prefix (defaults to \'wp_\').'
        ),
    )

    # class constant
    wp_prefix = 'wp_'

    def handle(self, *args, **options):
        """WordPress to Cyclope DataBase Migration Logic."""
        #TODO use transactions
        #connect to wordpress mysql database
        cnx = self._mysql_connection(options['server'], options['db'], options['user'], options['password'])
        self.wp_prefix = options['wp_prefix']
        
        #TODO clean cyclope sqlite database
        
        # SiteSettings <- wp_options
        # https://codex.wordpress.org/Option_Reference
        wp_options = ('siteurl', 'blogname', 'blogdescription', 'home', 'default_comment_status', 'comment_moderation', 'comments_notify')
        #TODO comment_registration, users_can_register, blog_public
        wp_options = self._fetch_wp_options(cnx, wp_options)
        settings = SiteSettings.objects.all()[0]
        settings.global_title = wp_options['blogname']
        settings.description = wp_options['blogdescription']
        #NOTE settings.keywords = WP doesn't use meta tags, only as a plugin
        settings.allow_comments = u'YES' if wp_options['default_comment_status']=='open' else u'NO'
        settings.moderate_comments = wp_options['comment_moderation']==1 #default False
        settings.enable_comments_notifications = wp_options['comments_notify'] in ('', 1) #default True
        site = settings.site
        site.name = wp_options['blogname']
        site.domain = wp_options['siteurl']
        site.save()
        settings.save()

        # Article <- wp_posts
        wp_post_fields = ('post_title', 'post_status', 'post_date', 'post_modified', 'comment_status', 'post_content', 'post_excerpt')
        wp_posts = self._fetch_wp_posts(cnx, wp_post_fields)
        articles = map(self._post_2_article, wp_posts)
        #cannot create in bulk because of auto slug
        for article in articles:
            article.save()

        #close mysql connection
        cnx.close()

    def _mysql_connection(self, host, database, user, password):
        """Establish a MySQL connection to the given option params and return it."""
        config = {
            'host': host,
            'database': database,
            'user': user
        }
        if not password is None : config['password']=password
        try:
            cnx = mysql.connector.connect(**config)
            return cnx
        except mysql.connector.Error as err:
            if err.errno == errorcode.ER_ACCESS_DENIED_ERROR:
                print "Wrong User name or Password."
            elif err.errno == errorcode.ER_BAD_DB_ERROR:
                print "Database doesn't exist."
            else:
                print err
            raise
        else:
            return cnx

    def _fetch_wp_options(self, mysql_cnx, options):
        """Execute single query to WP _options table to retrieve the given option names."""
        query = "SELECT option_name, option_value FROM "+self.wp_prefix+"options WHERE option_name IN {}".format(options)
        cursor = mysql_cnx.cursor()
        cursor.execute(query)
        results = dict(cursor.fetchall())
        cursor.close()
        return results

    #NOTE although this function uses the DB cursor, loading all posts to RAM could be heavyweight
    def _fetch_wp_posts(self, mysql_cnx, fields):
        """Queries the given fields to WP posts table selecting only posts, not pages nor attachments,
           Returns them in a list of dictionnaries."""
        query = re.sub("[()']", '', "SELECT {} FROM ".format(fields))+self.wp_prefix+"posts WHERE post_type='post'"
        cursor = mysql_cnx.cursor()
        cursor.execute(query)
        results = []
        for result in cursor :
            results.append(dict(zip(fields, result)))
        cursor.close()
        return results

    def _post_2_article(self, post):
        """Instances an Article object from a WP post hash."""
        return Article(
            name = post['post_title'],
            #post_name is AutoSlug
            text = post['post_content'],
            #date = post['post_date'], redundant
            creation_date = post['post_date'],
            modification_date = post['post_modified'],
            published = post['post_status']=='publish',#private and draft are unpublished
            allow_comments = post['comment_status']=='open',#all posts have a status, none imported default to SITE
            summary = post['post_excerpt']
            #pretitle has no equivalent in WP
            #TODO 
            #show_author=always user
            #FKs:
            #   user
            #   comments
            #   related_contents
            #   picture
            #   author
            #   source
        )


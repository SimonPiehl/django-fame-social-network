from django.urls import path

from socialnetwork.views.html import timeline
from socialnetwork.views.html import follow
from socialnetwork.views.html import unfollow
from socialnetwork.views.html import bullshitters # T6
from socialnetwork.views.html import toggle_community_mode, join_community, leave_community # T7
from socialnetwork.views.html import similar_users # T8
from socialnetwork.views.rest import PostsListApiView

app_name = "socialnetwork"

# URL patterns map URLs to their corresponding view functions.
# Each path() connects a URL to a view function
urlpatterns = [
    path("api/posts", PostsListApiView.as_view(), name="posts_fulllist"),
    path("html/timeline", timeline, name="timeline"),
    path("api/follow", follow, name="follow"),
    path("api/unfollow", unfollow, name="unfollow"),
    path("html/bullshitters", bullshitters, name="bullshitters"),   # T6
    path("html/toggle_community_mode", toggle_community_mode, name="toggle_community_mode"), # T7
    path("html/join_community", join_community, name="join_community"), # T7
    path("html/leave_community", leave_community, name="leave_community"), # T7
    path("html/similar_users", similar_users, name="similar_users"), # T8

]

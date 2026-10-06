import pytest

from studio.postid import PostRef, from_file_name, ig_pk, ig_shortcode


def test_a_snapinsta_name_gives_the_post_link_id_and_owner():
    ref = from_file_name("SnapInsta-Ai_3905594969719662453_44234418290.mp4")
    assert ref == PostRef(
        "instagram", "3905594969719662453", "DYzde6msWd1", "https://www.instagram.com/reel/DYzde6msWd1/", "44234418290"
    )


def test_a_shortcode_name_gives_the_same_kind_of_ref():
    ref = from_file_name("SnapInsta-Ai_Dd6TVXUgWqh.mp4")
    assert ref is not None and ref.shortcode == "Dd6TVXUgWqh" and ref.post_id == "3997592650277546657"
    assert ref.url == "https://www.instagram.com/reel/Dd6TVXUgWqh/" and ref.owner_id is None


@pytest.mark.parametrize(
    "copy", ["SnapInsta-Ai_3997177133468702953_1357791339 2.mp4", "SnapInsta-Ai_3997177133468702953_1357791339 (2).mp4"]
)
def test_a_second_copy_of_a_file_is_the_same_post(copy):
    first = from_file_name("SnapInsta-Ai_3997177133468702953_1357791339.mp4")
    assert first is not None and from_file_name(copy) == first


def test_the_name_may_come_with_a_folder_and_another_case():
    ref = from_file_name("/Users/x/Downloads/snapinsta-ai_4001422182254325982_26362222234.MOV")
    assert ref is not None and ref.shortcode == "DeH6EY5ozDe"


@pytest.mark.parametrize(
    "name",
    ["IMG_2041.MOV", "video.mp4", "SnapInsta-Ai_.mp4", "SnapInsta-Ai_123.mp4", "SnapInsta-Ai_abc$def.mp4",
     "SnapInsta-Ai_3905594969719662453_44234418290.jpg", "", "TikTok_7690275854697499918.mp4"],
)
def test_any_other_name_is_a_plain_file(name):
    assert from_file_name(name) is None


def test_the_shortcode_and_the_pk_are_the_same_number():
    for pk in (3905594969719662453, 4001422182254325982, 1):
        assert ig_pk(ig_shortcode(pk)) == pk
    with pytest.raises(ValueError):
        ig_pk("abc$")
    with pytest.raises(ValueError):
        ig_shortcode(0)

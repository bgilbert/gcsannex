==========================================
git-annex support for Google Cloud Storage
==========================================

This is a git-annex_ external special remote that supports Google Cloud
Storage (GCS).

.. _git-annex: https://git-annex.branchable.com/


Features
========

- Supports Standard, Durable Reduced Availability, and Nearline storage
  classes.
- Accesses Google Cloud Storage via a Google Cloud service account.  Does
  not use the Google Cloud Storage Interoperability API.
- Should support object sizes up to 5 TB.


License
=======

`GNU General Public License, version 3 or later`_.

.. _`GNU General Public License, version 3 or later`: http://www.gnu.org/licenses/gpl-3.0.en.html


Installing
==========

::

  pip install gcsannex


Configuring Google Cloud Storage
================================

1. Log into the `Google Developers Console`_.

2. Create a project if you don't already have one.  Remember its
   project ID.

3. In the project's settings, go to **API Manager** > **Credentials**.

4. Click "Create credentials", then "Service account key".  Select a
   service account (or create a new one), ensure "JSON" is selected, then
   click "Create".

5. A credentials file will be downloaded to your computer.  You will need
   this file when configuring gcsannex.

.. _`Google Developers Console`: https://console.developers.google.com/


Adding a remote
===============

::

  git annex initremote <remotename> type=external externaltype=gcs encryption={none|shared|pubkey|hybrid} project=<gcs-project-id>

Set the ``GOOGLE_APPLICATION_CREDENTIALS`` environment variable to the
path to your credentials file.  This is only necessary when running
``initremote``; afterward, git-annex will remember your credentials.


Mandatory settings
------------------

``encryption``
  See the `git-annex encryption documentation`_.

``project``
  Your project ID from the Google developer console.

.. _`git-annex encryption documentation`: http://git-annex.branchable.com/encryption/


Optional settings
-----------------

``bucket``
  The bucket name, which must be globally unique within GCS.  The default
  name is based on the remote name and UUID.

``chunk``
  Enable chunking_.

``embedcreds``
  Set to ``yes`` to commit the login credentials to the Git repository
  so other clones can read them.  When using GPG encryption, the default is
  ``yes`` and the credentials are stored encrypted.  Otherwise, the default
  is ``no``; if set to ``yes``, anyone with access to the repo can also
  access the GCS bucket.

``fileprefix``
  A string, such as ``mydata/``, to be prepended to the name of each object.
  This allows a bucket to be shared by multiple remotes.

``location``
  The physical location for the data.  Can be any of the `location strings`_
  supported by GCS, such as ``ASIA``, ``EU``, or ``US``.  Defaults to ``US``.

``public``
  If ``yes``, newly-uploaded objects are made publicly readable.  Defaults
  to ``no``.

``readonly``
  If set to ``true`` when enabling an existing ``public`` remote, files
  can be retrieved without GCS credentials and without gcsannex installed.
  Requires development version of git-annex.

``storageclass``
  A `storage class`_ supported by GCS, such as ``STANDARD``,
  ``DURABLE_REDUCED_AVAILABILITY``, or ``NEARLINE``.  Defaults to
  ``STANDARD``.

.. _chunking: http://git-annex.branchable.com/chunking/
.. _`location strings`: https://cloud.google.com/storage/docs/bucket-locations
.. _`storage class`: https://cloud.google.com/storage/docs/storage-classes

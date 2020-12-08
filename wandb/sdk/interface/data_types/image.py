class Image(BatchableMedia):
    """
        Wandb class for images.

        Arguments:
            data_or_path (numpy array, string, io): Accepts numpy array of
                image data, or a PIL image. The class attempts to infer
                the data format and converts it.
            mode (string): The PIL mode for an image. Most common are "L", "RGB",
                "RGBA". Full explanation at https://pillow.readthedocs.io/en/4.2.x/handbook/concepts.html#concept-modes.
            caption (string): Label for display of image.
    """

    MAX_ITEMS = 108

    # PIL limit
    MAX_DIMENSION = 65500

    artifact_type = "image-file"

    def __init__(
        self,
        data_or_path,
        mode=None,
        caption=None,
        grouping=None,
        classes=None,
        boxes=None,
        masks=None,
    ):
        super(Image, self).__init__()
        # TODO: We should remove grouping, it's a terrible name and I don't
        # think anyone uses it.

        self._grouping = None
        self._caption = None
        self._width = None
        self._height = None
        self._image = None
        self._classes = None
        self._boxes = None
        self._masks = None

        # Allows the user to pass an Image object as the first parameter and have a perfect copy,
        # only overriding additional metdata passed in. If this pattern is compelling, we can generalize.
        if isinstance(data_or_path, Image):
            self._grouping = data_or_path._grouping
            self._caption = data_or_path._caption
            self._width = data_or_path._width
            self._height = data_or_path._height
            self._image = data_or_path._image
            self._classes = data_or_path._classes
            self._path = data_or_path._path
            self._is_tmp = data_or_path._is_tmp
            self._extension = data_or_path._extension
            self._sha256 = data_or_path._sha256
            self._size = data_or_path._size
            self.format = data_or_path.format
            self.artifact_source = data_or_path.artifact_source

            # We do not want to implicitly copy boxes or masks, just the image-related data.
            # self._boxes = data_or_path._boxes
            # self._masks = data_or_path._masks
        else:
            PILImage = util.get_module(
                "PIL.Image",
                required='wandb.Image needs the PIL package. To get it, run "pip install pillow".',
            )
            if isinstance(data_or_path, six.string_types):
                self._set_file(data_or_path, is_tmp=False)
                self._image = PILImage.open(data_or_path)
                self._image.load()
                ext = os.path.splitext(data_or_path)[1][1:]
                self.format = ext
            else:
                data = data_or_path

                if util.is_matplotlib_typename(util.get_full_typename(data)):
                    buf = six.BytesIO()
                    util.ensure_matplotlib_figure(data).savefig(buf)
                    self._image = PILImage.open(buf)
                elif isinstance(data, PILImage.Image):
                    self._image = data
                elif util.is_pytorch_tensor_typename(util.get_full_typename(data)):
                    vis_util = util.get_module(
                        "torchvision.utils", "torchvision is required to render images"
                    )
                    if hasattr(data, "requires_grad") and data.requires_grad:
                        data = data.detach()
                    data = vis_util.make_grid(data, normalize=True)
                    self._image = PILImage.fromarray(
                        data.mul(255)
                        .clamp(0, 255)
                        .byte()
                        .permute(1, 2, 0)
                        .cpu()
                        .numpy()
                    )
                else:
                    if hasattr(data, "numpy"):  # TF data eager tensors
                        data = data.numpy()
                    if data.ndim > 2:
                        data = (
                            data.squeeze()
                        )  # get rid of trivial dimensions as a convenience
                    self._image = PILImage.fromarray(
                        self.to_uint8(data), mode=mode or self.guess_mode(data)
                    )

                tmp_path = os.path.join(MEDIA_TMP.name, util.generate_id() + ".png")
                self.format = "png"
                self._image.save(tmp_path, transparency=None)
                self._set_file(tmp_path, is_tmp=True)

        if grouping is not None:
            self._grouping = grouping

        if caption is not None:
            self._caption = caption

        if classes is not None:
            if not isinstance(classes, Classes):
                self._classes = Classes(classes)
            else:
                self._classes = classes

        if boxes:
            if not isinstance(boxes, dict):
                raise ValueError('Images "boxes" argument must be a dictionary')
            boxes_final = {}
            for key in boxes:
                if isinstance(boxes[key], BoundingBoxes2D):
                    boxes_final[key] = boxes[key]
                else:
                    boxes_final[key] = BoundingBoxes2D(boxes[key], key)
            self._boxes = boxes_final

        if masks:
            if not isinstance(masks, dict):
                raise ValueError('Images "masks" argument must be a dictionary')
            masks_final = {}
            for key in masks:
                if isinstance(masks[key], ImageMask):
                    masks_final[key] = masks[key]
                else:
                    masks_final[key] = ImageMask(masks[key], key)
            self._masks = masks_final

        self._width, self._height = self._image.size

    @classmethod
    def from_json(cls, json_obj, source_artifact):
        classes = None
        if json_obj.get("classes") is not None:
            classes = source_artifact.get(json_obj["classes"]["path"])

        _masks = None
        masks = json_obj.get("masks")
        if masks:
            _masks = {}
            for key in masks:
                _masks[key] = ImageMask.from_json(masks[key], source_artifact)
                _masks[key].artifact_source = {"artifact": source_artifact}
                _masks[key]._key = key

        boxes = json_obj.get("boxes")
        _boxes = None
        if boxes:
            _boxes = {}
            for key in boxes:
                _boxes[key] = BoundingBoxes2D.from_json(boxes[key], source_artifact)
                _boxes[key]._key = key

        return cls(
            source_artifact.get_path(json_obj["path"]).download(),
            caption=json_obj.get("caption"),
            grouping=json_obj.get("grouping"),
            classes=classes,
            boxes=_boxes,
            masks=_masks,
        )

    @classmethod
    def get_media_subdir(cls):
        return os.path.join("media", "images")

    def bind_to_run(self, *args, **kwargs):
        super(Image, self).bind_to_run(*args, **kwargs)
        id_ = kwargs.get("id_")
        if self._boxes is not None:
            for i, k in enumerate(self._boxes):
                kwargs["id_"] = "{}{}".format(id_, i) if id_ is not None else None
                self._boxes[k].bind_to_run(*args, **kwargs)

        if self._masks is not None:
            for i, k in enumerate(self._masks):
                kwargs["id_"] = "{}{}".format(id_, i) if id_ is not None else None
                self._masks[k].bind_to_run(*args, **kwargs)

    def to_json(self, run_or_artifact):
        json_dict = super(Image, self).to_json(run_or_artifact)
        json_dict["_type"] = Image.artifact_type
        json_dict["format"] = self.format

        if self._width is not None:
            json_dict["width"] = self._width
        if self._height is not None:
            json_dict["height"] = self._height
        if self._grouping:
            json_dict["grouping"] = self._grouping
        if self._caption:
            json_dict["caption"] = self._caption

        wandb_run, wandb_artifacts = _safe_sdk_import()

        if isinstance(run_or_artifact, wandb_artifacts.Artifact):
            artifact = run_or_artifact
            if (self._masks != None or self._boxes != None) and self._classes is None:
                raise ValueError(
                    "classes must be passed to wandb.Image which have masks or bounding boxes when adding to artifacts"
                )

            if self._classes is not None:
                # Here, rather than give each class definition it's own name (and entry), we
                # purposely are giving a non-unique class name of /media/cls.classes.json.
                # This may create user confusion if if multiple different class definitions
                # are expected in a single artifact. However, we want to catch this user pattern
                # if it exists and dive deeper. The alternative code is provided below.
                #
                class_name = os.path.join("media", "cls")
                #
                # class_name = os.path.join(
                #     "media", "classes", os.path.basename(self._path) + "_cls"
                # )
                #
                classes_entry = artifact.add(self._classes, class_name)
                json_dict["classes"] = {
                    "type": "classes-file",
                    "path": classes_entry.path,
                    "digest": classes_entry.digest,
                }

        elif not isinstance(run_or_artifact, wandb_run.Run):
            raise ValueError("to_json accepts wandb_run.Run or wandb_artifact.Artifact")

        if self._boxes:
            json_dict["boxes"] = {
                k: box.to_json(run_or_artifact) for (k, box) in self._boxes.items()
            }
        if self._masks:
            json_dict["masks"] = {
                k: mask.to_json(run_or_artifact) for (k, mask) in self._masks.items()
            }
        return json_dict

    def guess_mode(self, data):
        """
        Guess what type of image the np.array is representing
        """
        # TODO: do we want to support dimensions being at the beginning of the array?
        if data.ndim == 2:
            return "L"
        elif data.shape[-1] == 3:
            return "RGB"
        elif data.shape[-1] == 4:
            return "RGBA"
        else:
            raise ValueError(
                "Un-supported shape for image conversion %s" % list(data.shape)
            )

    @classmethod
    def to_uint8(self, data):
        """
        Converts floating point image on the range [0,1] and integer images
        on the range [0,255] to uint8, clipping if necessary.
        """
        np = util.get_module(
            "numpy",
            required="wandb.Image requires numpy if not supplying PIL Images: pip install numpy",
        )

        # I think it's better to check the image range vs the data type, since many
        # image libraries will return floats between 0 and 255

        # some images have range -1...1 or 0-1
        dmin = np.min(data)
        if dmin < 0:
            data = (data - np.min(data)) / np.ptp(data)
        if np.max(data) <= 1.0:
            data = (data * 255).astype(np.int32)

        # assert issubclass(data.dtype.type, np.integer), 'Illegal image format.'
        return data.clip(0, 255).astype(np.uint8)

    @classmethod
    def seq_to_json(cls, images, run, key, step):
        """
        Combines a list of images into a meta dictionary object describing the child images.
        """

        jsons = [obj.to_json(run) for obj in images]

        media_dir = cls.get_media_subdir()

        for obj in jsons:
            expected = util.to_forward_slash_path(media_dir)
            if not obj["path"].startswith(expected):
                raise ValueError(
                    "Files in an array of Image's must be in the {} directory, not {}".format(
                        cls.get_media_subdir(), obj["path"]
                    )
                )

        num_images_to_log = len(images)
        width, height = images[0]._image.size
        format = jsons[0]["format"]

        def size_equals_image(image):
            img_width, img_height = image._image.size
            return img_width == width and img_height == height

        sizes_match = all(size_equals_image(img) for img in images)
        if not sizes_match:
            logging.warning(
                "Images sizes do not match. This will causes images to be display incorrectly in the UI."
            )

        meta = {
            "_type": "images/separated",
            "width": width,
            "height": height,
            "format": format,
            "count": num_images_to_log,
        }

        captions = Image.all_captions(images)

        if captions:
            meta["captions"] = captions

        all_masks = Image.all_masks(images, run, key, step)

        if all_masks:
            meta["all_masks"] = all_masks

        all_boxes = Image.all_boxes(images, run, key, step)

        if all_boxes:
            meta["all_boxes"] = all_boxes

        return meta

    @classmethod
    def all_masks(cls, images, run, run_key, step):
        all_mask_groups = []
        for image in images:
            if image._masks:
                mask_group = {}
                for k in image._masks:
                    mask = image._masks[k]
                    mask_group[k] = mask.to_json(run)
                all_mask_groups.append(mask_group)
            else:
                all_mask_groups.append(None)
        if all_mask_groups and not all(x is None for x in all_mask_groups):
            return all_mask_groups
        else:
            return False

    @classmethod
    def all_boxes(cls, images, run, run_key, step):
        all_box_groups = []
        for image in images:
            if image._boxes:
                box_group = {}
                for k in image._boxes:
                    box = image._boxes[k]
                    box_group[k] = box.to_json(run)
                all_box_groups.append(box_group)
            else:
                all_box_groups.append(None)
        if all_box_groups and not all(x is None for x in all_box_groups):
            return all_box_groups
        else:
            return False

    @classmethod
    def all_captions(cls, images):
        if images[0]._caption != None:
            return [i._caption for i in images]
        else:
            return False

    def __ne__(self, other):
        return not self.__eq__(other)

    def __eq__(self, other):
        return (
            self._grouping == other._grouping
            and self._caption == other._caption
            and self._width == other._width
            and self._height == other._height
            and self._image == other._image
            and self._classes == other._classes
        )
